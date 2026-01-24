//! Tile scheduler with parallel I/O and prefetching.

use std::path::PathBuf;

/// Maximum number of visible tiles to load in a single prefetch batch.
/// Higher values ensure complete coverage at low zoom, but increase I/O load.
const MAX_VISIBLE_TILES: usize = 256;

/// Budget for extended (non-visible) prefetch tiles.
/// These are tiles just outside the viewport for smooth panning.
const EXTENDED_TILE_BUDGET: usize = 32;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::thread;

use crossbeam_channel::{bounded, Receiver, Sender};
use parking_lot::RwLock;
use rayon::prelude::*;

use crate::cache::{CacheStats, TileCache, TileCoord};
use crate::decoder::{decode_tile, TileData};
use crate::error::{TileError, TileResult};
use crate::format::{SlideMetadata, TilePathResolver};
use crate::prefetch::{PrefetchCalculator, PrefetchConfig, Viewport};

/// Prefetch request sent to the background worker.
struct PrefetchRequest {
    viewport: Viewport,
}

/// Internal slide state.
struct SlideState {
    metadata: SlideMetadata,
    resolver: TilePathResolver,
}

/// High-performance tile scheduler with caching and prefetching.
pub struct TileScheduler {
    /// Tile cache.
    cache: Arc<TileCache>,
    /// Currently loaded slide state.
    slide: RwLock<Option<SlideState>>,
    /// Prefetch calculator.
    prefetch_calc: PrefetchCalculator,
    /// Channel to send prefetch requests to background worker.
    prefetch_tx: Sender<PrefetchRequest>,
    /// Flag to signal shutdown.
    shutdown: Arc<AtomicBool>,
    /// Background prefetch thread handle.
    prefetch_handle: Option<thread::JoinHandle<()>>,
}

impl TileScheduler {
    /// Create a new scheduler.
    ///
    /// # Arguments
    /// * `cache_size_mb` - Maximum cache size in megabytes
    /// * `prefetch_distance` - Number of tiles to prefetch ahead
    pub fn new(cache_size_mb: usize, prefetch_distance: u32) -> Self {
        let cache = Arc::new(TileCache::new(cache_size_mb));
        let shutdown = Arc::new(AtomicBool::new(false));

        let prefetch_config = PrefetchConfig {
            tiles_ahead: prefetch_distance,
            ..Default::default()
        };
        let prefetch_calc = PrefetchCalculator::new(prefetch_config);

        // Create channel for prefetch requests
        let (prefetch_tx, prefetch_rx) = bounded::<PrefetchRequest>(4);

        // Spawn background prefetch worker
        let worker_cache = Arc::clone(&cache);
        let worker_shutdown = Arc::clone(&shutdown);

        let prefetch_handle = Some(thread::spawn(move || {
            Self::prefetch_worker(worker_cache, prefetch_rx, worker_shutdown);
        }));

        Self {
            cache,
            slide: RwLock::new(None),
            prefetch_calc,
            prefetch_tx,
            shutdown,
            prefetch_handle,
        }
    }

    /// Background worker that processes prefetch requests.
    ///
    /// Currently a placeholder for future async prefetching. The worker receives
    /// viewport updates but actual prefetching is done synchronously in
    /// `prefetch_for_viewport()` which has access to slide state. This worker
    /// architecture is preserved to enable future improvements like:
    /// - Decoupled prefetch timing from UI thread
    /// - Speculative prefetching based on velocity prediction
    /// - Background cache warming during idle periods
    fn prefetch_worker(
        _cache: Arc<TileCache>,
        rx: Receiver<PrefetchRequest>,
        shutdown: Arc<AtomicBool>,
    ) {
        while !shutdown.load(Ordering::Relaxed) {
            match rx.recv_timeout(std::time::Duration::from_millis(100)) {
                Ok(_request) => {
                    // TODO: Implement async prefetching here when slide state
                    // can be safely accessed from background thread
                }
                Err(crossbeam_channel::RecvTimeoutError::Timeout) => continue,
                Err(crossbeam_channel::RecvTimeoutError::Disconnected) => break,
            }
        }
    }

    /// Load a .fastpath directory.
    pub fn load(&self, path: &str) -> TileResult<()> {
        let path = PathBuf::from(path);

        if !path.exists() {
            return Err(TileError::IoError(std::io::Error::new(
                std::io::ErrorKind::NotFound,
                format!("Path does not exist: {}", path.display()),
            )));
        }

        let metadata = SlideMetadata::load(&path)?;
        let resolver = TilePathResolver::new(path, &metadata)?;

        // Clear cache when loading a new slide
        self.cache.clear();

        let mut slide = self.slide.write();
        *slide = Some(SlideState { metadata, resolver });

        Ok(())
    }

    /// Close the current slide.
    pub fn close(&self) {
        let mut slide = self.slide.write();
        *slide = None;
        self.cache.clear();
    }

    /// Check if a slide is loaded.
    pub fn is_loaded(&self) -> bool {
        self.slide.read().is_some()
    }

    /// Get tile size.
    pub fn tile_size(&self) -> u32 {
        self.slide
            .read()
            .as_ref()
            .map(|s| s.metadata.tile_size)
            .unwrap_or(512)
    }

    /// Get number of pyramid levels.
    pub fn num_levels(&self) -> usize {
        self.slide
            .read()
            .as_ref()
            .map(|s| s.metadata.num_levels())
            .unwrap_or(0)
    }

    /// Get slide dimensions.
    pub fn dimensions(&self) -> (u32, u32) {
        self.slide
            .read()
            .as_ref()
            .map(|s| s.metadata.dimensions)
            .unwrap_or((0, 0))
    }

    /// Get a tile, loading from disk if not cached.
    ///
    /// Returns the tile data or None if the tile doesn't exist.
    pub fn get_tile(&self, level: u32, col: u32, row: u32) -> Option<TileData> {
        let coord = TileCoord::new(level, col, row);

        // Check cache first
        if let Some(tile) = self.cache.get(&coord) {
            return Some(tile);
        }

        // Load from disk
        let tile_path = {
            let slide = self.slide.read();
            slide.as_ref()?.resolver.get_tile_path(level, col, row)?
        };

        match decode_tile(&tile_path) {
            Ok(tile) => {
                self.cache.insert(coord, tile.clone());
                Some(tile)
            }
            Err(e) => {
                eprintln!(
                    "[TILE ERROR] Failed to load {}/{}_{}; path={:?}: {:?}",
                    level, col, row, tile_path, e
                );
                None
            }
        }
    }

    /// Update viewport and trigger prefetching.
    pub fn update_viewport(
        &self,
        x: f64,
        y: f64,
        width: f64,
        height: f64,
        scale: f64,
        velocity_x: f64,
        velocity_y: f64,
    ) {
        let viewport = Viewport::new(x, y, width, height, scale, velocity_x, velocity_y);

        // Send to background worker (non-blocking)
        let _ = self.prefetch_tx.try_send(PrefetchRequest {
            viewport: viewport.clone(),
        });

        // Also do immediate prefetching for visible tiles
        self.prefetch_for_viewport(&viewport);
    }

    /// Prefetch tiles for a viewport.
    fn prefetch_for_viewport(&self, viewport: &Viewport) {
        let slide = self.slide.read();
        let Some(state) = slide.as_ref() else {
            return;
        };

        // Get visible tiles first (these are the priority)
        let visible_tiles = self.prefetch_calc.visible_tiles(&state.metadata, viewport);
        let visible_uncached: Vec<_> = visible_tiles
            .into_iter()
            .filter(|coord| !self.cache.contains(coord))
            .collect();

        // Get all tiles to prefetch (includes visible + extended viewport)
        let all_tiles = self.prefetch_calc.prefetch_tiles(
            &state.metadata,
            viewport,
            &|coord| self.cache.contains(coord),
        );

        // Adaptive batch sizing:
        // - Load ALL visible tiles (up to MAX_VISIBLE_TILES) to avoid gray screen at low zoom
        // - Then add extended tiles up to EXTENDED_TILE_BUDGET
        let visible_count = visible_uncached.len().min(MAX_VISIBLE_TILES);
        let extended_budget =
            EXTENDED_TILE_BUDGET.saturating_sub(visible_count.min(EXTENDED_TILE_BUDGET));

        let mut tiles_to_load = Vec::with_capacity(visible_count + extended_budget);

        // Add all visible tiles first (priority)
        tiles_to_load.extend(visible_uncached.into_iter().take(MAX_VISIBLE_TILES));

        // Add extended tiles that aren't already in the list
        for coord in all_tiles {
            if tiles_to_load.len() >= visible_count + extended_budget {
                break;
            }
            if !tiles_to_load.contains(&coord) {
                tiles_to_load.push(coord);
            }
        }

        if tiles_to_load.is_empty() {
            return;
        }

        // Resolve paths while holding the lock
        let tile_paths: Vec<_> = tiles_to_load
            .iter()
            .filter_map(|coord| {
                state
                    .resolver
                    .get_tile_path(coord.level, coord.col, coord.row)
                    .map(|path| (*coord, path))
            })
            .collect();

        // Drop the lock before parallel loading
        drop(slide);

        // Load tiles in parallel using rayon
        let cache = &self.cache;
        tile_paths.par_iter().for_each(|(coord, path)| {
            // Skip if already cached (another thread might have loaded it)
            if cache.contains(coord) {
                return;
            }

            if let Ok(tile) = decode_tile(path) {
                cache.insert(*coord, tile);
            }
        });
    }

    /// Pre-warm cache with ALL tiles from levels that have few tiles.
    /// This ensures any initial viewport zoom has tiles ready.
    /// Prefetches all levels where total_tiles <= MAX_TILES_PER_LEVEL.
    pub fn prefetch_low_res_levels(&self) {
        // 64 tiles = 8x8 grid, covers levels 3+ for most slides.
        // Small enough for fast loading, large enough for smooth initial zoom.
        const MAX_TILES_PER_LEVEL: u32 = 64;

        let slide = self.slide.read();
        let Some(state) = slide.as_ref() else { return };

        let num_levels = state.metadata.num_levels();

        // Prefetch all levels where tile count is manageable
        // Start from lowest resolution and work up
        let mut levels_to_prefetch = Vec::new();
        for level in (0..num_levels).rev() {
            if let Some(level_info) = state.metadata.get_level(level as u32) {
                let total_tiles = level_info.cols * level_info.rows;
                if total_tiles <= MAX_TILES_PER_LEVEL {
                    levels_to_prefetch.push(level as u32);
                }
            }
        }

        let mut tile_paths = Vec::new();
        for level in &levels_to_prefetch {
            if let Some(level_info) = state.metadata.get_level(*level) {
                for row in 0..level_info.rows {
                    for col in 0..level_info.cols {
                        if let Some(path) = state.resolver.get_tile_path(*level, col, row) {
                            tile_paths.push((TileCoord::new(*level, col, row), path));
                        }
                    }
                }
            }
        }

        eprintln!(
            "[PREFETCH] Loading {} tiles from {} levels (max {} tiles/level): {:?}",
            tile_paths.len(),
            levels_to_prefetch.len(),
            MAX_TILES_PER_LEVEL,
            levels_to_prefetch
        );

        drop(slide);

        let cache = &self.cache;
        let loaded = std::sync::atomic::AtomicUsize::new(0);
        let failed = std::sync::atomic::AtomicUsize::new(0);

        tile_paths.par_iter().for_each(|(coord, path)| {
            if !cache.contains(coord) {
                match decode_tile(path) {
                    Ok(tile) => {
                        cache.insert(*coord, tile);
                        loaded.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
                    }
                    Err(e) => {
                        eprintln!(
                            "[PREFETCH ERROR] {}/{}_{}; path={:?}: {:?}",
                            coord.level, coord.col, coord.row, path, e
                        );
                        failed.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
                    }
                }
            }
        });

        eprintln!(
            "[PREFETCH] Done: {} loaded, {} failed",
            loaded.load(std::sync::atomic::Ordering::Relaxed),
            failed.load(std::sync::atomic::Ordering::Relaxed)
        );
    }

    /// Check if a tile is in the cache without loading it.
    pub fn is_tile_cached(&self, level: u32, col: u32, row: u32) -> bool {
        let coord = TileCoord::new(level, col, row);
        self.cache.contains(&coord)
    }

    /// Check which tiles from a list are cached.
    /// Returns a vector of (level, col, row) for tiles that are in cache.
    pub fn filter_cached_tiles(&self, tiles: &[(u32, u32, u32)]) -> Vec<(u32, u32, u32)> {
        tiles
            .iter()
            .filter(|(level, col, row)| {
                let coord = TileCoord::new(*level, *col, *row);
                self.cache.contains(&coord)
            })
            .copied()
            .collect()
    }

    /// Get cache statistics.
    pub fn cache_stats(&self) -> CacheStats {
        self.cache.stats()
    }

    /// Get metadata for Python access.
    pub fn get_metadata(&self) -> Option<(u32, u32, u32, usize, f64, f64)> {
        let slide = self.slide.read();
        slide.as_ref().map(|s| {
            (
                s.metadata.dimensions.0,
                s.metadata.dimensions.1,
                s.metadata.tile_size,
                s.metadata.num_levels(),
                s.metadata.target_mpp,
                s.metadata.target_magnification,
            )
        })
    }

    /// Get level info for Python access.
    pub fn get_level_info(&self, level: u32) -> Option<(u32, u32, u32)> {
        let slide = self.slide.read();
        slide.as_ref().and_then(|s| {
            s.metadata
                .get_level(level)
                .map(|l| (l.downsample, l.cols, l.rows))
        })
    }
}

impl Drop for TileScheduler {
    fn drop(&mut self) {
        // Signal shutdown
        self.shutdown.store(true, Ordering::Relaxed);

        // Wait for background thread to finish
        if let Some(handle) = self.prefetch_handle.take() {
            let _ = handle.join();
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use tempfile::TempDir;

    fn create_test_fastpath(dir: &std::path::Path) {
        // Create metadata.json
        let metadata = r#"{
            "dimensions": [2048, 2048],
            "tile_size": 512,
            "levels": [
                {"level": 0, "downsample": 1, "cols": 4, "rows": 4},
                {"level": 1, "downsample": 2, "cols": 2, "rows": 2}
            ],
            "target_mpp": 0.5,
            "target_magnification": 20.0,
            "tile_format": "traditional"
        }"#;

        fs::write(dir.join("metadata.json"), metadata).unwrap();

        // Create levels directory structure
        fs::create_dir_all(dir.join("levels/0")).unwrap();
        fs::create_dir_all(dir.join("levels/1")).unwrap();
    }

    #[test]
    fn test_scheduler_creation() {
        let scheduler = TileScheduler::new(512, 2);
        assert!(!scheduler.is_loaded());
    }

    #[test]
    fn test_load_and_close() {
        let temp = TempDir::new().unwrap();
        create_test_fastpath(temp.path());

        let scheduler = TileScheduler::new(512, 2);
        scheduler.load(temp.path().to_str().unwrap()).unwrap();

        assert!(scheduler.is_loaded());
        assert_eq!(scheduler.tile_size(), 512);
        assert_eq!(scheduler.num_levels(), 2);
        assert_eq!(scheduler.dimensions(), (2048, 2048));

        scheduler.close();
        assert!(!scheduler.is_loaded());
    }

    #[test]
    fn test_load_nonexistent() {
        let scheduler = TileScheduler::new(512, 2);
        let result = scheduler.load("/nonexistent/path");
        assert!(result.is_err());
    }

    #[test]
    fn test_get_tile_not_loaded() {
        let scheduler = TileScheduler::new(512, 2);
        let tile = scheduler.get_tile(0, 0, 0);
        assert!(tile.is_none());
    }

    #[test]
    fn test_cache_stats() {
        let scheduler = TileScheduler::new(512, 2);
        let stats = scheduler.cache_stats();
        assert_eq!(stats.hits, 0);
        assert_eq!(stats.misses, 0);
    }
}
