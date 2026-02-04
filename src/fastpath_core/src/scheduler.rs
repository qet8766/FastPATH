//! Tile scheduler with parallel I/O and prefetching.

use std::collections::HashSet;
use std::path::PathBuf;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use std::time::Instant;

use parking_lot::{Mutex, RwLock};
use rayon::prelude::*;

/// Maximum number of visible tiles to load in a single prefetch batch.
/// Set to 256 to cover a 4K display (3840x2160) at any zoom level:
/// at 512px tiles that's ~8x4=32 visible tiles, with generous headroom
/// for HiDPI scaling and partial-tile overlap at edges.
const MAX_VISIBLE_TILES: usize = 256;

/// Budget for extended (non-visible) prefetch tiles beyond the viewport.
/// These tiles provide smooth panning by pre-loading one tile ring outside
/// the visible area, covering ~32 tiles for a typical viewport perimeter.
const EXTENDED_TILE_BUDGET: usize = 32;

use crate::bulk_preload::BulkPreloader;
use crate::cache::{CacheStats, CompressedTileCache, SlideTileCoord, TileCache, TileCoord, compute_slide_id};
use crate::decoder::{decode_jpeg_bytes, CompressedTileData, TileData};
use crate::error::{TileError, TileResult};
use crate::pack::TilePack;
use crate::prefetch::{PrefetchCalculator, PrefetchConfig, Viewport};
use crate::slide_pool::{SlideEntry, SlidePool};

/// Combined L1 + L2 cache statistics.
#[derive(Debug, Clone, Default)]
pub struct CombinedCacheStats {
    pub l1: CacheStats,
    pub l2: CacheStats,
}

/// Check if per-tile timing instrumentation is enabled via env var.
fn tile_timing_enabled() -> bool {
    std::env::var("FASTPATH_TILE_TIMING").is_ok_and(|v| v == "1" || v == "true")
}

/// High-performance tile scheduler with caching and prefetching.
pub struct TileScheduler {
    /// L1 tile cache (decoded RGB).
    cache: Arc<TileCache>,
    /// L2 compressed tile cache (JPEG bytes, persists across slide switches).
    l2_cache: Arc<CompressedTileCache>,
    /// Currently loaded slide state (Arc shared with pool).
    slide: RwLock<Option<Arc<SlideEntry>>>,
    /// Metadata pool — caches SlideEntry across slide switches.
    pool: Arc<SlidePool>,
    /// Prefetch calculator.
    prefetch_calc: PrefetchCalculator,
    /// Tiles currently being decoded — prevents duplicate work across rayon threads.
    in_flight: Mutex<HashSet<TileCoord>>,
    /// Monotonic counter bumped on load()/close() to invalidate stale prefetch batches.
    generation: AtomicU64,
    /// Hash of the current slide path (0 = no slide loaded).
    active_slide_id: AtomicU64,
    /// Background preloader for filling L2 with tiles from nearby slides.
    bulk_preloader: BulkPreloader,
    /// Whether per-tile timing is enabled (cached from FASTPATH_TILE_TIMING env var).
    tile_timing: bool,
}

impl TileScheduler {
    /// Create a new scheduler.
    ///
    /// # Arguments
    /// * `cache_size_mb` - Maximum L1 cache size in megabytes (decoded RGB tiles)
    /// * `l2_cache_size_mb` - Maximum L2 cache size in megabytes (compressed JPEG bytes)
    /// * `prefetch_distance` - Number of tiles to prefetch ahead
    pub fn new(cache_size_mb: usize, l2_cache_size_mb: usize, prefetch_distance: u32) -> Self {
        let cache = Arc::new(TileCache::new(cache_size_mb));
        let l2_cache = Arc::new(CompressedTileCache::new(l2_cache_size_mb));

        let prefetch_config = PrefetchConfig {
            tiles_ahead: prefetch_distance,
            ..Default::default()
        };
        let prefetch_calc = PrefetchCalculator::new(prefetch_config);

        let pool = Arc::new(SlidePool::new());
        let bulk_preloader = BulkPreloader::new(
            Arc::clone(&l2_cache),
            Arc::clone(&pool),
        );

        Self {
            cache,
            l2_cache,
            slide: RwLock::new(None),
            pool,
            prefetch_calc,
            in_flight: Mutex::new(HashSet::new()),
            generation: AtomicU64::new(0),
            active_slide_id: AtomicU64::new(0),
            bulk_preloader,
            tile_timing: tile_timing_enabled(),
        }
    }

    /// Invalidate in-flight prefetch work and clear L1 cache.
    ///
    /// Bumps the generation counter first so prefetch workers see the change
    /// before the cache is cleared, preventing stale tiles from being inserted
    /// into the fresh cache. L2 is NOT touched — it persists across slides.
    fn invalidate_current(&self) {
        self.generation.fetch_add(1, Ordering::Release);
        self.in_flight.lock().clear();
        self.cache.clear();
    }

    /// Load a .fastpath directory.
    pub fn load(&self, path: &str) -> TileResult<()> {
        let path_buf = PathBuf::from(path);

        if !path_buf.exists() {
            return Err(TileError::Io(std::io::Error::new(
                std::io::ErrorKind::NotFound,
                format!("Path does not exist: {}", path_buf.display()),
            )));
        }

        // Canonicalize for stable slide_id on Windows
        // (C:\slides\foo vs C:/slides/foo vs c:\SLIDES\FOO → same ID)
        let canonical = path_buf.canonicalize().map_err(TileError::Io)?;
        let slide_id = compute_slide_id(&canonical.to_string_lossy().to_lowercase());

        let entry = self.pool.load_or_get(slide_id, &path_buf)?;

        self.invalidate_current();

        let mut slide = self.slide.write();
        *slide = Some(entry);

        self.active_slide_id.store(slide_id, Ordering::Release);
        Ok(())
    }

    /// Close the current slide.
    pub fn close(&self) {
        self.invalidate_current();
        let mut slide = self.slide.write();
        *slide = None;
        self.active_slide_id.store(0, Ordering::Release);
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

    /// Log a tile error to stderr.
    fn log_tile_error(phase: &str, coord: &TileCoord, error: &dyn std::fmt::Debug) {
        eprintln!("[TILE ERROR] {phase}{coord}: {error:?}");
    }

    /// Read, compress-cache (L2), decode, and insert a tile into L1.
    ///
    /// Called only from foreground `get_tile()` — does NOT use in-flight dedup.
    /// The caller has already checked the cache, so we decode unconditionally.
    /// If a prefetch thread is concurrently decoding the same tile, both will
    /// produce valid data and moka handles duplicate inserts safely. This avoids
    /// returning `None` to QML (which would cache a placeholder permanently).
    /// Background prefetch dedup is handled separately in `load_tile_for_prefetch()`.
    fn load_tile_into_cache(&self, coord: &TileCoord, pack: &TilePack) -> Option<TileData> {
        let slide_id = self.active_slide_id.load(Ordering::Acquire);
        let t0 = if self.tile_timing { Some(Instant::now()) } else { None };

        let tile_ref = pack.tile_ref(coord.level, coord.col, coord.row)?;

        // Step 1: Read compressed JPEG from pack
        let compressed = match pack.read_tile_bytes(tile_ref) {
            Ok(bytes) => CompressedTileData {
                jpeg_bytes: bytes,
                width: 0,
                height: 0,
            },
            Err(e) => {
                Self::log_tile_error("", coord, &e);
                return None;
            }
        };
        let t_read = t0.map(|t| t.elapsed());

        // Step 2: Insert into L2 (side effect, O(1) Bytes clone)
        if slide_id != 0 {
            let l2_coord = SlideTileCoord::new(slide_id, coord.level, coord.col, coord.row);
            self.l2_cache.insert(l2_coord, compressed.clone());
        }
        let t_l2 = t0.map(|t| t.elapsed());

        // Step 3: Decode JPEG → RGB, insert into L1
        match decode_jpeg_bytes(&compressed) {
            Ok(tile) => {
                let t_decode = t0.map(|t| t.elapsed());
                self.cache.insert(*coord, tile.clone());

                if let Some(t) = t0 {
                    let total = t.elapsed();
                    eprintln!(
                        "[TILE TIMING] {coord}  pack={:.2?} l2={:.2?} decode={:.2?} total={:.2?}",
                        t_read.unwrap(),
                        t_l2.unwrap() - t_read.unwrap(),
                        t_decode.unwrap() - t_l2.unwrap(),
                        total
                    );
                }
                Some(tile)
            }
            Err(e) => {
                Self::log_tile_error("decode ", coord, &e);
                None
            }
        }
    }

    /// Decode a tile for prefetch, respecting generation to discard stale work.
    ///
    /// Three generation checks prevent inserting tiles from an old slide:
    /// 1. Before claiming in-flight — quick exit without locking
    /// 2. After claiming — catches races where load() ran between check #1 and lock
    /// 3. Before L1 cache insert — the critical guard after the ~5-10ms decode
    ///
    /// L2 insert is guarded by slide_id consistency: only insert if the current
    /// slide_id still matches what we captured at the start, preventing stale
    /// prefetch threads from filing data under a new slide's ID.
    fn load_tile_for_prefetch(
        &self,
        coord: &TileCoord,
        pack: &TilePack,
        batch_generation: u64,
    ) -> Option<TileData> {
        // Capture slide_id + generation together at the start
        let slide_id = self.active_slide_id.load(Ordering::Acquire);

        // Check 1: quick exit before touching the in-flight set
        if self.generation.load(Ordering::Acquire) != batch_generation {
            return None;
        }

        // Fast path — tile already cached in L1
        if let Some(tile) = self.cache.get(coord) {
            return Some(tile);
        }

        // L2 hit — decode compressed JPEG and promote to L1, skip pack entirely
        if slide_id != 0 {
            let l2_coord = SlideTileCoord::new(slide_id, coord.level, coord.col, coord.row);
            if let Some(compressed) = self.l2_cache.get(&l2_coord) {
                // Generation check before decode
                if self.generation.load(Ordering::Acquire) != batch_generation {
                    return None;
                }
                if let Ok(tile) = decode_jpeg_bytes(&compressed) {
                    // Generation check after decode (the critical guard)
                    if self.generation.load(Ordering::Acquire) != batch_generation {
                        return None;
                    }
                    self.cache.insert(*coord, tile.clone());
                    return Some(tile);
                }
                // Decode failed — fall through to pack path
            }
        }

        // Claim this coord in the in-flight set
        {
            let mut flight = self.in_flight.lock();

            // Check 2: generation may have changed while waiting for lock
            if self.generation.load(Ordering::Acquire) != batch_generation {
                return None;
            }

            if !flight.insert(*coord) {
                return None;
            }
        }

        let tile_ref = match pack.tile_ref(coord.level, coord.col, coord.row) {
            Some(tile_ref) => tile_ref,
            None => {
                self.clear_in_flight_for_generation(coord, batch_generation);
                return None;
            }
        };

        // Step 1: Read compressed JPEG from pack
        let compressed = match pack.read_tile_bytes(tile_ref) {
            Ok(bytes) => CompressedTileData {
                jpeg_bytes: bytes,
                width: 0,
                height: 0,
            },
            Err(e) => {
                Self::log_tile_error("", coord, &e);
                self.clear_in_flight_for_generation(coord, batch_generation);
                return None;
            }
        };

        // Step 2: L2 insert — guarded by slide_id consistency
        // Only insert if the current slide_id still matches what we captured,
        // preventing stale prefetch threads from filing data under wrong slide
        let current_slide_id = self.active_slide_id.load(Ordering::Acquire);
        if slide_id != 0 && current_slide_id == slide_id {
            let l2_coord = SlideTileCoord::new(slide_id, coord.level, coord.col, coord.row);
            self.l2_cache.insert(l2_coord, compressed.clone());
        }

        // Step 3: Decode JPEG → RGB + L1 insert (generation-guarded)
        let result = match decode_jpeg_bytes(&compressed) {
            Ok(tile) => {
                // Check 3: generation may have changed during decode
                if self.generation.load(Ordering::Acquire) != batch_generation {
                    None
                } else {
                    self.cache.insert(*coord, tile.clone());
                    Some(tile)
                }
            }
            Err(e) => {
                Self::log_tile_error("decode ", coord, &e);
                None
            }
        };

        self.clear_in_flight_for_generation(coord, batch_generation);

        result
    }

    /// Remove an in-flight coord only if the generation still matches.
    /// Avoids clearing new-generation in-flight markers from stale prefetch threads.
    fn clear_in_flight_for_generation(&self, coord: &TileCoord, batch_generation: u64) {
        if self.generation.load(Ordering::Acquire) == batch_generation {
            self.in_flight.lock().remove(coord);
        }
    }

    /// Get a tile, loading from pack if not cached.
    ///
    /// Returns the tile data or None if the tile doesn't exist.
    pub fn get_tile(&self, level: u32, col: u32, row: u32) -> Option<TileData> {
        let coord = TileCoord::new(level, col, row);

        // L1 hit
        if let Some(tile) = self.cache.get(&coord) {
            return Some(tile);
        }

        // L2 hit — decode compressed JPEG and promote to L1
        let slide_id = self.active_slide_id.load(Ordering::Acquire);
        if slide_id != 0 {
            let l2_coord = SlideTileCoord::new(slide_id, level, col, row);
            if let Some(compressed) = self.l2_cache.get(&l2_coord) {
                if let Ok(tile) = decode_jpeg_bytes(&compressed) {
                    self.cache.insert(coord, tile.clone());
                    return Some(tile);
                }
                // Decode failed — fall through to pack
            }
        }

        // Load from pack
        let entry = {
            let slide = self.slide.read();
            Arc::clone(slide.as_ref()?)
        };

        self.load_tile_into_cache(&coord, &entry.pack)
    }

    /// Update viewport and trigger prefetching.
    #[allow(clippy::too_many_arguments)]
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
        self.prefetch_for_viewport(&viewport);
    }

    /// Prefetch tiles for a viewport.
    fn prefetch_for_viewport(&self, viewport: &Viewport) {
        let batch_generation = self.generation.load(Ordering::Acquire);

        let slide = self.slide.read();
        let Some(state) = slide.as_ref() else {
            return;
        };
        let state = Arc::clone(state);

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

        let target = visible_count + extended_budget;
        let mut tiles_to_load = Vec::with_capacity(target);

        // Add all visible tiles first (priority)
        tiles_to_load.extend(visible_uncached.into_iter().take(visible_count));

        // `prefetch_tiles()` returns tiles ordered by priority and starts with the
        // same uncached-visible set we just added, so we can skip that prefix
        // without doing an O(n^2) `contains()` scan here.
        if tiles_to_load.len() < target {
            tiles_to_load.extend(
                all_tiles
                    .into_iter()
                    .skip(visible_count)
                    .take(target - tiles_to_load.len()),
            );
        }

        if tiles_to_load.is_empty() {
            return;
        }

        // Drop the lock before parallel loading
        drop(slide);
        let pack = &state.pack;

        // Load tiles in parallel using rayon (generation-checked)
        tiles_to_load.par_iter().for_each(|coord| {
            self.load_tile_for_prefetch(coord, pack, batch_generation);
        });
    }

    /// Pre-warm cache with ALL tiles from levels that have few tiles.
    /// This ensures any initial viewport zoom has tiles ready.
    /// Prefetches all levels where total_tiles <= MAX_TILES_PER_LEVEL.
    pub fn prefetch_low_res_levels(&self) {
        // 64 tiles = 8x8 grid — covers the 3-4 lowest-resolution levels of
        // a typical 100k×100k slide. Keeps warm-up I/O under ~2 MB total
        // (64 × ~30 KB JPEG) while guaranteeing tiles are ready for any
        // initial zoom level the user might land on.
        const MAX_TILES_PER_LEVEL: u32 = 64;

        let batch_generation = self.generation.load(Ordering::Acquire);

        let slide = self.slide.read();
        let Some(state) = slide.as_ref() else { return };
        let state = Arc::clone(state);

        let num_levels = state.metadata.num_levels();

        // Prefetch all levels where tile count is manageable (single pass)
        // Start from lowest resolution (level 0 in dzsave convention) and work up
        let mut levels_to_prefetch = Vec::new();
        let mut all_coords = Vec::new();
        for level in 0..num_levels {
            if let Some(level_info) = state.metadata.get_level(level as u32) {
                if level_info.cols * level_info.rows <= MAX_TILES_PER_LEVEL {
                    levels_to_prefetch.push(level as u32);
                    for row in 0..level_info.rows {
                        for col in 0..level_info.cols {
                            all_coords.push(TileCoord::new(level as u32, col, row));
                        }
                    }
                }
            }
        }

        eprintln!(
            "[PREFETCH] Loading {} tiles from {} levels (max {} tiles/level): {:?}",
            all_coords.len(),
            levels_to_prefetch.len(),
            MAX_TILES_PER_LEVEL,
            levels_to_prefetch
        );

        drop(slide);
        let pack = &state.pack;

        let loaded = std::sync::atomic::AtomicUsize::new(0);
        let failed = std::sync::atomic::AtomicUsize::new(0);

        all_coords.par_iter().for_each(|coord| {
            // Skip tiles already in cache — only count fresh loads
            if self.cache.contains(coord) {
                return;
            }
            if self.load_tile_for_prefetch(coord, pack, batch_generation).is_some() {
                loaded.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
            } else {
                failed.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
            }
        });

        eprintln!(
            "[PREFETCH] Done: {} loaded, {} failed",
            loaded.load(std::sync::atomic::Ordering::Relaxed),
            failed.load(std::sync::atomic::Ordering::Relaxed)
        );
    }

    /// Check which tiles from a list are cached.
    /// Returns a vector of (level, col, row) for tiles that are in cache.
    pub fn filter_cached_tiles(&self, tiles: &[(u32, u32, u32)]) -> Vec<(u32, u32, u32)> {
        let slide_id = self.active_slide_id.load(Ordering::Acquire);
        tiles
            .iter()
            .filter(|(level, col, row)| {
                let coord = TileCoord::new(*level, *col, *row);
                if self.cache.contains(&coord) {
                    return true;
                }
                if slide_id != 0 {
                    let l2_coord = SlideTileCoord::new(slide_id, *level, *col, *row);
                    return self.l2_cache.contains(&l2_coord);
                }
                false
            })
            .copied()
            .collect()
    }

    /// Get combined L1 + L2 cache statistics.
    pub fn cache_stats(&self) -> CombinedCacheStats {
        CombinedCacheStats {
            l1: self.cache.stats(),
            l2: self.l2_cache.stats(),
        }
    }

    /// Reset cache hit/miss counters to zero (both L1 and L2).
    pub fn reset_cache_stats(&self) {
        self.cache.reset_stats();
        self.l2_cache.reset_stats();
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

    /// Start background preloading of slides into L2.
    ///
    /// `slide_paths` should be in priority order (current slide first,
    /// then alternating outward). Each path is canonicalized and hashed
    /// to compute a slide_id for L2 keying.
    pub fn start_bulk_preload(&self, slide_paths: Vec<String>) {
        let entries: Vec<(u64, PathBuf)> = slide_paths
            .into_iter()
            .filter_map(|p| {
                let path = PathBuf::from(&p);
                let canonical = path.canonicalize().ok()?;
                let slide_id =
                    compute_slide_id(&canonical.to_string_lossy().to_lowercase());
                Some((slide_id, path))
            })
            .collect();

        self.bulk_preloader.start(entries);
    }

    /// Cancel any running bulk preload.
    pub fn cancel_bulk_preload(&self) {
        self.bulk_preloader.cancel();
    }

    /// Whether a bulk preload is currently running.
    pub fn is_bulk_preloading(&self) -> bool {
        self.bulk_preloader.is_running()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::test_utils::{create_test_fastpath, test_compressed_tile};
    use tempfile::TempDir;

    #[test]
    fn test_scheduler_creation() {
        let scheduler = TileScheduler::new(512, 64, 2);
        assert!(!scheduler.is_loaded());
    }

    #[test]
    fn test_load_and_close() {
        let temp = TempDir::new().unwrap();
        create_test_fastpath(temp.path());

        let scheduler = TileScheduler::new(512, 64, 2);
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
        let scheduler = TileScheduler::new(512, 64, 2);
        let result = scheduler.load("/nonexistent/path");
        assert!(result.is_err());
    }

    #[test]
    fn test_get_tile_not_loaded() {
        let scheduler = TileScheduler::new(512, 64, 2);
        let tile = scheduler.get_tile(0, 0, 0);
        assert!(tile.is_none());
    }

    #[test]
    fn test_cache_stats() {
        let scheduler = TileScheduler::new(512, 64, 2);
        let stats = scheduler.cache_stats();
        assert_eq!(stats.l1.hits, 0);
        assert_eq!(stats.l1.misses, 0);
        assert_eq!(stats.l2.hits, 0);
        assert_eq!(stats.l2.misses, 0);
    }

    #[test]
    fn test_in_flight_cleanup_on_prefetch_error() {
        let temp = TempDir::new().unwrap();
        create_test_fastpath(temp.path());
        let pack = crate::pack::TilePack::open(temp.path()).unwrap();

        let scheduler = TileScheduler::new(512, 64, 2);
        let coord = TileCoord::new(0, 0, 0);
        let gen = scheduler.generation.load(Ordering::Acquire);
        // Tile is missing in the pack, but in-flight must still be cleaned up
        let result = scheduler.load_tile_for_prefetch(
            &coord,
            &pack,
            gen,
        );
        assert!(result.is_none());
        assert!(scheduler.in_flight.lock().is_empty());
    }

    #[test]
    fn test_foreground_bypasses_in_flight() {
        let temp = TempDir::new().unwrap();
        create_test_fastpath(temp.path());
        let pack = crate::pack::TilePack::open(temp.path()).unwrap();

        let scheduler = TileScheduler::new(512, 64, 2);
        let coord = TileCoord::new(0, 0, 0);
        // Simulate a prefetch thread holding the coord in-flight
        scheduler.in_flight.lock().insert(coord);
        // Foreground load_tile_into_cache should still attempt decode (not return None).
        // Tile is missing in the pack, but the point is it tried instead of bailing.
        let result = scheduler.load_tile_into_cache(&coord, &pack);
        // Result is None due to missing tile, NOT due to in-flight skip
        assert!(result.is_none());
        // The foreground path does not touch in_flight, so the entry remains
        assert!(scheduler.in_flight.lock().contains(&coord));
    }

    #[test]
    fn test_generation_increments() {
        let temp = TempDir::new().unwrap();
        create_test_fastpath(temp.path());

        let scheduler = TileScheduler::new(512, 64, 2);
        assert_eq!(scheduler.generation.load(Ordering::Acquire), 0);

        scheduler.load(temp.path().to_str().unwrap()).unwrap();
        assert_eq!(scheduler.generation.load(Ordering::Acquire), 1);

        scheduler.load(temp.path().to_str().unwrap()).unwrap();
        assert_eq!(scheduler.generation.load(Ordering::Acquire), 2);

        scheduler.close();
        assert_eq!(scheduler.generation.load(Ordering::Acquire), 3);
    }

    #[test]
    fn test_in_flight_cleanup_respects_generation() {
        let scheduler = TileScheduler::new(512, 64, 2);
        let coord = TileCoord::new(0, 0, 0);

        // Stale generation should not remove a new-generation in-flight marker.
        let old_gen = scheduler.generation.load(Ordering::Acquire);
        scheduler.generation.fetch_add(1, Ordering::Release);
        scheduler.in_flight.lock().insert(coord);
        scheduler.clear_in_flight_for_generation(&coord, old_gen);
        assert!(scheduler.in_flight.lock().contains(&coord));

        // Current generation should remove.
        let current_gen = scheduler.generation.load(Ordering::Acquire);
        scheduler.clear_in_flight_for_generation(&coord, current_gen);
        assert!(scheduler.in_flight.lock().is_empty());
    }

    #[test]
    fn test_in_flight_cleared_on_load() {
        let temp = TempDir::new().unwrap();
        create_test_fastpath(temp.path());

        let scheduler = TileScheduler::new(512, 64, 2);
        // Manually insert a coord into in-flight
        scheduler.in_flight.lock().insert(TileCoord::new(0, 99, 99));
        assert!(!scheduler.in_flight.lock().is_empty());

        scheduler.load(temp.path().to_str().unwrap()).unwrap();
        assert!(scheduler.in_flight.lock().is_empty());
    }

    #[test]
    fn test_in_flight_cleared_on_close() {
        let scheduler = TileScheduler::new(512, 64, 2);
        scheduler.in_flight.lock().insert(TileCoord::new(0, 99, 99));
        assert!(!scheduler.in_flight.lock().is_empty());

        scheduler.close();
        assert!(scheduler.in_flight.lock().is_empty());
    }

    #[test]
    fn test_stale_generation_skips_load() {
        let temp = TempDir::new().unwrap();
        create_test_fastpath(temp.path());
        let pack = crate::pack::TilePack::open(temp.path()).unwrap();

        let scheduler = TileScheduler::new(512, 64, 2);
        scheduler.load(temp.path().to_str().unwrap()).unwrap();
        // generation is now 1

        let coord = TileCoord::new(0, 0, 0);
        // Use stale generation (0) — should return None without touching cache
        let result = scheduler.load_tile_for_prefetch(
            &coord,
            &pack,
            0, // stale
        );
        assert!(result.is_none());
        assert!(scheduler.in_flight.lock().is_empty());
        assert!(!scheduler.cache.contains(&coord));
    }

    #[test]
    fn test_l2_not_cleared_on_load() {
        let temp = TempDir::new().unwrap();
        create_test_fastpath(temp.path());

        let scheduler = TileScheduler::new(512, 64, 2);
        scheduler.load(temp.path().to_str().unwrap()).unwrap();

        // Manually insert an L2 entry
        let l2_coord = SlideTileCoord::new(42, 0, 0, 0);
        let compressed = crate::decoder::CompressedTileData {
            jpeg_bytes: bytes::Bytes::from(vec![0u8; 100]),
            width: 512,
            height: 512,
        };
        scheduler.l2_cache.insert(l2_coord, compressed);

        // Reload — L2 should survive
        scheduler.load(temp.path().to_str().unwrap()).unwrap();

        assert!(scheduler.l2_cache.contains(&l2_coord));
    }

    #[test]
    fn test_l2_not_cleared_on_close() {
        let temp = TempDir::new().unwrap();
        create_test_fastpath(temp.path());

        let scheduler = TileScheduler::new(512, 64, 2);
        scheduler.load(temp.path().to_str().unwrap()).unwrap();

        // Manually insert an L2 entry
        let l2_coord = SlideTileCoord::new(42, 0, 0, 0);
        let compressed = crate::decoder::CompressedTileData {
            jpeg_bytes: bytes::Bytes::from(vec![0u8; 100]),
            width: 512,
            height: 512,
        };
        scheduler.l2_cache.insert(l2_coord, compressed);

        // Close — L2 should survive
        scheduler.close();

        assert!(scheduler.l2_cache.contains(&l2_coord));
    }

    #[test]
    fn test_active_slide_id_lifecycle() {
        let temp = TempDir::new().unwrap();
        create_test_fastpath(temp.path());

        let scheduler = TileScheduler::new(512, 64, 2);

        // Before load: 0
        assert_eq!(scheduler.active_slide_id.load(Ordering::Acquire), 0);

        // After load: nonzero
        scheduler.load(temp.path().to_str().unwrap()).unwrap();
        let slide_id = scheduler.active_slide_id.load(Ordering::Acquire);
        assert_ne!(slide_id, 0);

        // After close: 0
        scheduler.close();
        assert_eq!(scheduler.active_slide_id.load(Ordering::Acquire), 0);

        // After reload: nonzero (same path → same id)
        scheduler.load(temp.path().to_str().unwrap()).unwrap();
        let slide_id2 = scheduler.active_slide_id.load(Ordering::Acquire);
        assert_ne!(slide_id2, 0);
        assert_eq!(slide_id, slide_id2);
    }

    // --- L2 read path tests ---

    #[test]
    fn test_get_tile_l2_hit() {
        let scheduler = TileScheduler::new(512, 64, 2);
        let slide_id: u64 = 42;
        scheduler.active_slide_id.store(slide_id, Ordering::Release);

        // Insert valid compressed tile into L2
        let l2_coord = SlideTileCoord::new(slide_id, 0, 0, 0);
        scheduler.l2_cache.insert(l2_coord, test_compressed_tile());


        // get_tile should find it in L2, decode, and promote to L1
        let tile = scheduler.get_tile(0, 0, 0);
        assert!(tile.is_some());

        // Verify L1 promotion
        let coord = TileCoord::new(0, 0, 0);
        assert!(scheduler.cache.contains(&coord));
    }

    #[test]
    fn test_prefetch_l2_hit() {
        let temp = TempDir::new().unwrap();
        create_test_fastpath(temp.path());
        let pack = crate::pack::TilePack::open(temp.path()).unwrap();

        let scheduler = TileScheduler::new(512, 64, 2);
        let slide_id: u64 = 42;
        scheduler.active_slide_id.store(slide_id, Ordering::Release);
        let gen = scheduler.generation.load(Ordering::Acquire);

        // Insert valid compressed tile into L2
        let l2_coord = SlideTileCoord::new(slide_id, 0, 0, 0);
        scheduler.l2_cache.insert(l2_coord, test_compressed_tile());


        let coord = TileCoord::new(0, 0, 0);
        let tile = scheduler.load_tile_for_prefetch(
            &coord,
            &pack, // pack not used — L2 hit
            gen,
        );
        assert!(tile.is_some());

        // Verify L1 promotion
        assert!(scheduler.cache.contains(&coord));

        // Verify in-flight was NOT used (L2 path bypasses in-flight)
        assert!(scheduler.in_flight.lock().is_empty());
    }

    #[test]
    fn test_prefetch_l2_generation_guard() {
        let temp = TempDir::new().unwrap();
        create_test_fastpath(temp.path());
        let pack = crate::pack::TilePack::open(temp.path()).unwrap();

        let scheduler = TileScheduler::new(512, 64, 2);
        let slide_id: u64 = 42;
        scheduler.active_slide_id.store(slide_id, Ordering::Release);

        // Insert valid compressed tile into L2
        let l2_coord = SlideTileCoord::new(slide_id, 0, 0, 0);
        scheduler.l2_cache.insert(l2_coord, test_compressed_tile());


        // Bump generation to make stale_gen stale
        let stale_gen = scheduler.generation.load(Ordering::Acquire);
        scheduler.generation.fetch_add(1, Ordering::Release);

        let coord = TileCoord::new(0, 0, 0);
        let tile = scheduler.load_tile_for_prefetch(
            &coord,
            &pack,
            stale_gen,
        );
        // Should return None — generation mismatch before L2 decode
        assert!(tile.is_none());

        // L1 should NOT have been populated
        assert!(!scheduler.cache.contains(&coord));
    }

    #[test]
    fn test_filter_cached_tiles_includes_l2() {
        let scheduler = TileScheduler::new(512, 64, 2);
        let slide_id: u64 = 42;
        scheduler.active_slide_id.store(slide_id, Ordering::Release);

        // Insert into L2 only (not L1)
        let l2_coord = SlideTileCoord::new(slide_id, 0, 1, 2);
        scheduler.l2_cache.insert(l2_coord, test_compressed_tile());


        let tiles = vec![(0, 1, 2), (0, 99, 99)];
        let cached = scheduler.filter_cached_tiles(&tiles);

        assert_eq!(cached.len(), 1);
        assert_eq!(cached[0], (0, 1, 2));
    }

    #[test]
    fn test_filter_cached_tiles_no_slide() {
        let scheduler = TileScheduler::new(512, 64, 2);
        // slide_id is 0 (no slide loaded)

        // Insert into L2 under some slide_id — should NOT be found
        let l2_coord = SlideTileCoord::new(42, 0, 1, 2);
        scheduler.l2_cache.insert(l2_coord, test_compressed_tile());


        let tiles = vec![(0, 1, 2)];
        let cached = scheduler.filter_cached_tiles(&tiles);

        assert!(cached.is_empty());
    }

    #[test]
    fn test_l2_decode_failure_falls_through() {
        let temp = TempDir::new().unwrap();
        create_test_fastpath(temp.path());

        let scheduler = TileScheduler::new(512, 64, 2);
        scheduler.load(temp.path().to_str().unwrap()).unwrap();
        let slide_id = scheduler.active_slide_id.load(Ordering::Acquire);

        // Insert corrupted bytes into L2
        let l2_coord = SlideTileCoord::new(slide_id, 0, 0, 0);
        let corrupted = crate::decoder::CompressedTileData {
            jpeg_bytes: bytes::Bytes::from(b"not a jpeg".to_vec()),
            width: 0,
            height: 0,
        };
        scheduler.l2_cache.insert(l2_coord, corrupted);


        // get_tile should fail L2 decode, fall through to pack.
        // Pack will also fail (missing tile), so result is None.
        let tile = scheduler.get_tile(0, 0, 0);
        assert!(tile.is_none());
    }

    // --- SlidePool integration tests ---

    #[test]
    fn test_load_reuses_pool_on_revisit() {
        let temp = TempDir::new().unwrap();
        create_test_fastpath(temp.path());

        let scheduler = TileScheduler::new(512, 64, 2);
        scheduler.load(temp.path().to_str().unwrap()).unwrap();
        scheduler.close();
        scheduler.load(temp.path().to_str().unwrap()).unwrap();

        // Pool should have exactly one entry (same slide reused)
        assert_eq!(scheduler.pool.len(), 1);
    }

    #[test]
    fn test_close_preserves_pool_entry() {
        let temp = TempDir::new().unwrap();
        create_test_fastpath(temp.path());

        let scheduler = TileScheduler::new(512, 64, 2);
        scheduler.load(temp.path().to_str().unwrap()).unwrap();
        scheduler.close();

        // Pool entry survives close()
        assert_eq!(scheduler.pool.len(), 1);
    }

    #[test]
    fn test_load_different_slides_grows_pool() {
        let temp_a = TempDir::new().unwrap();
        let temp_b = TempDir::new().unwrap();
        create_test_fastpath(temp_a.path());
        create_test_fastpath(temp_b.path());

        let scheduler = TileScheduler::new(512, 64, 2);
        scheduler.load(temp_a.path().to_str().unwrap()).unwrap();
        scheduler.load(temp_b.path().to_str().unwrap()).unwrap();

        assert_eq!(scheduler.pool.len(), 2);
    }
}
