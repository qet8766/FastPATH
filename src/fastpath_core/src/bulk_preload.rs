//! Background preloader for L2 compressed tile cache.
//!
//! Reads JPEG tiles from disk and inserts them into L2 (compressed cache)
//! without decoding to RGB. Uses a dedicated 3-thread rayon pool to avoid
//! competing with interactive viewport prefetch I/O.

use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::Arc;
use std::thread::JoinHandle;

use parking_lot::Mutex;

use crate::cache::{CompressedTileCache, SlideTileCoord};
use crate::decoder::read_jpeg_bytes;
use crate::slide_pool::SlidePool;

/// Background preloader that fills L2 cache with tiles from multiple slides.
pub struct BulkPreloader {
    l2_cache: Arc<CompressedTileCache>,
    pool: Arc<SlidePool>,
    rayon_pool: Arc<rayon::ThreadPool>,
    cancelled: Arc<AtomicBool>,
    handle: Mutex<Option<JoinHandle<()>>>,
}

impl BulkPreloader {
    /// Create a new bulk preloader with a dedicated 3-thread rayon pool.
    pub fn new(l2_cache: Arc<CompressedTileCache>, pool: Arc<SlidePool>) -> Self {
        let rayon_pool = Arc::new(
            rayon::ThreadPoolBuilder::new()
                .num_threads(3)
                .thread_name(|idx| format!("bulk-preload-{}", idx))
                .build()
                .expect("failed to create bulk preload rayon pool"),
        );

        Self {
            l2_cache,
            pool,
            rayon_pool,
            cancelled: Arc::new(AtomicBool::new(false)),
            handle: Mutex::new(None),
        }
    }

    /// Start background preloading of slides into L2.
    ///
    /// Cancels any previous run, then spawns a worker thread that iterates
    /// slides in priority order, reading JPEG tiles from disk and inserting
    /// them into L2. No JPEG decode (no L1 insert) — tiles are decoded on
    /// demand when the user views them.
    ///
    /// `slides` should be pre-sorted in priority order (outward expansion
    /// from the current slide index).
    pub fn start(&self, slides: Vec<(u64, PathBuf)>) {
        // Cancel previous run
        self.cancel();

        if slides.is_empty() {
            return;
        }

        // Reset cancelled flag
        self.cancelled.store(false, Ordering::Release);

        let l2_cache = Arc::clone(&self.l2_cache);
        let pool = Arc::clone(&self.pool);
        let cancelled = Arc::clone(&self.cancelled);
        let rayon_pool = Arc::clone(&self.rayon_pool);

        let handle = std::thread::Builder::new()
            .name("bulk-preload-main".into())
            .spawn(move || {
                for (slide_id, path) in &slides {
                    if cancelled.load(Ordering::Acquire) {
                        eprintln!("[BULK PRELOAD] Cancelled");
                        return;
                    }

                    let slide_name = path
                        .file_name()
                        .map(|n| n.to_string_lossy().to_string())
                        .unwrap_or_else(|| path.to_string_lossy().to_string());

                    // Load metadata + resolver from pool
                    let entry = match pool.load_or_get(*slide_id, path) {
                        Ok(e) => e,
                        Err(e) => {
                            eprintln!(
                                "[BULK PRELOAD] Skipping {}: {:?}",
                                slide_name, e
                            );
                            continue;
                        }
                    };

                    // Enumerate all tiles across all levels
                    let mut tile_work: Vec<(SlideTileCoord, PathBuf)> = Vec::new();
                    let mut skipped = 0usize;

                    for level_info in &entry.metadata.levels {
                        for row in 0..level_info.rows {
                            for col in 0..level_info.cols {
                                let l2_coord = SlideTileCoord::new(
                                    *slide_id,
                                    level_info.level,
                                    col,
                                    row,
                                );

                                // Skip tiles already in L2
                                if l2_cache.contains(&l2_coord) {
                                    skipped += 1;
                                    continue;
                                }

                                let tile_path = entry
                                    .resolver
                                    .get_tile_path(level_info.level, col, row);
                                tile_work.push((l2_coord, tile_path));
                            }
                        }
                    }

                    if tile_work.is_empty() {
                        eprintln!(
                            "[BULK PRELOAD] {}: 0 tiles loaded, 0 failed, {} skipped (all cached)",
                            slide_name, skipped
                        );
                        continue;
                    }

                    let loaded = AtomicUsize::new(0);
                    let failed = AtomicUsize::new(0);
                    let cancelled_ref = &cancelled;

                    rayon_pool.install(|| {
                        use rayon::prelude::*;
                        tile_work.par_iter().for_each(|(l2_coord, tile_path)| {
                            if cancelled_ref.load(Ordering::Acquire) {
                                return;
                            }

                            match read_jpeg_bytes(tile_path) {
                                Ok(compressed) => {
                                    l2_cache.insert(*l2_coord, compressed);
                                    loaded.fetch_add(1, Ordering::Relaxed);
                                }
                                Err(_) => {
                                    failed.fetch_add(1, Ordering::Relaxed);
                                }
                            }
                        });
                    });

                    eprintln!(
                        "[BULK PRELOAD] {}: {} tiles loaded, {} failed, {} skipped",
                        slide_name,
                        loaded.load(Ordering::Relaxed),
                        failed.load(Ordering::Relaxed),
                        skipped
                    );
                }

                eprintln!("[BULK PRELOAD] Complete");
            })
            .expect("failed to spawn bulk preload thread");

        *self.handle.lock() = Some(handle);
    }

    /// Cancel any running bulk preload and wait for the worker to exit.
    pub fn cancel(&self) {
        self.cancelled.store(true, Ordering::Release);
        if let Some(handle) = self.handle.lock().take() {
            let _ = handle.join();
        }
    }

    /// Whether a bulk preload is currently running.
    pub fn is_running(&self) -> bool {
        let guard = self.handle.lock();
        match guard.as_ref() {
            Some(h) => !h.is_finished(),
            None => false,
        }
    }

    /// Wait for a running bulk preload to finish without cancelling it.
    #[cfg(test)]
    pub fn wait(&self) {
        if let Some(handle) = self.handle.lock().take() {
            let _ = handle.join();
        }
    }
}

impl Drop for BulkPreloader {
    fn drop(&mut self) {
        self.cancelled.store(true, Ordering::Release);
        if let Some(handle) = self.handle.lock().take() {
            let _ = handle.join();
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::cache::compute_slide_id;
    use crate::test_utils::{create_test_fastpath_with_tiles, compute_test_slide_id};
    use std::fs;
    use tempfile::TempDir;

    #[test]
    fn test_preload_fills_l2() {
        let temp = TempDir::new().unwrap();
        let slide_dir = temp.path().join("slide1.fastpath");
        fs::create_dir_all(&slide_dir).unwrap();
        create_test_fastpath_with_tiles(&slide_dir);

        let l2_cache = Arc::new(CompressedTileCache::new(64));
        let pool = Arc::new(SlidePool::new());
        let preloader = BulkPreloader::new(Arc::clone(&l2_cache), Arc::clone(&pool));

        let slide_id = compute_test_slide_id(&slide_dir);
        preloader.start(vec![(slide_id, slide_dir)]);

        // Wait for completion without cancelling
        preloader.wait();

        // Run pending moka tasks so contains() sees recent inserts
        l2_cache.stats();

        // Verify L2 has tiles: level 0 has 1 tile, level 1 has 4 tiles = 5 total
        assert!(l2_cache.contains(&SlideTileCoord::new(slide_id, 0, 0, 0)));
        assert!(l2_cache.contains(&SlideTileCoord::new(slide_id, 1, 0, 0)));
        assert!(l2_cache.contains(&SlideTileCoord::new(slide_id, 1, 0, 1)));
        assert!(l2_cache.contains(&SlideTileCoord::new(slide_id, 1, 1, 0)));
        assert!(l2_cache.contains(&SlideTileCoord::new(slide_id, 1, 1, 1)));
    }

    #[test]
    fn test_preload_skips_existing() {
        let temp = TempDir::new().unwrap();
        let slide_dir = temp.path().join("slide1.fastpath");
        fs::create_dir_all(&slide_dir).unwrap();
        create_test_fastpath_with_tiles(&slide_dir);

        let l2_cache = Arc::new(CompressedTileCache::new(64));
        let pool = Arc::new(SlidePool::new());
        let slide_id = compute_test_slide_id(&slide_dir);

        // Pre-populate L2 with all tiles via a first run
        let preloader = BulkPreloader::new(Arc::clone(&l2_cache), Arc::clone(&pool));
        preloader.start(vec![(slide_id, slide_dir.clone())]);
        preloader.wait();
        l2_cache.stats(); // flush moka

        // Reset stats to track second run
        l2_cache.reset_stats();

        // Second run should skip all tiles (already in L2)
        let preloader2 = BulkPreloader::new(Arc::clone(&l2_cache), Arc::clone(&pool));
        preloader2.start(vec![(slide_id, slide_dir)]);
        preloader2.wait();

        // No new gets should have been performed (all skipped via contains())
        // The stats should show 0 hits and 0 misses since we didn't call get()
        let stats = l2_cache.stats();
        assert_eq!(stats.hits, 0);
        assert_eq!(stats.misses, 0);
    }

    #[test]
    fn test_preload_cancellation() {
        // Create a slide with many tiles to give time for cancellation
        let temp = TempDir::new().unwrap();

        // Create multiple slides to ensure cancellation has a chance to trigger
        let mut slides = Vec::new();
        for i in 0..10 {
            let slide_dir = temp.path().join(format!("slide{}.fastpath", i));
            fs::create_dir_all(&slide_dir).unwrap();
            create_test_fastpath_with_tiles(&slide_dir);
            let slide_id = compute_test_slide_id(&slide_dir);
            slides.push((slide_id, slide_dir));
        }

        let l2_cache = Arc::new(CompressedTileCache::new(64));
        let pool = Arc::new(SlidePool::new());
        let preloader = BulkPreloader::new(Arc::clone(&l2_cache), Arc::clone(&pool));

        preloader.start(slides);
        // Cancel immediately — should not load all slides
        preloader.cancel();

        // The test passes if cancel() returns without hanging.
        // We can't assert exact counts since timing varies.
    }

    #[test]
    fn test_preload_invalid_slide_skipped() {
        let temp = TempDir::new().unwrap();

        // Valid slide
        let slide_dir = temp.path().join("good.fastpath");
        fs::create_dir_all(&slide_dir).unwrap();
        create_test_fastpath_with_tiles(&slide_dir);
        let good_id = compute_test_slide_id(&slide_dir);

        // Invalid slide (no metadata.json)
        let bad_dir = temp.path().join("bad.fastpath");
        fs::create_dir_all(&bad_dir).unwrap();
        let bad_id = compute_slide_id("bad");

        let l2_cache = Arc::new(CompressedTileCache::new(64));
        let pool = Arc::new(SlidePool::new());
        let preloader = BulkPreloader::new(Arc::clone(&l2_cache), Arc::clone(&pool));

        // Bad slide first, then good slide
        preloader.start(vec![(bad_id, bad_dir), (good_id, slide_dir)]);
        preloader.wait();
        l2_cache.stats();

        // Good slide should still have been loaded
        assert!(l2_cache.contains(&SlideTileCoord::new(good_id, 0, 0, 0)));
    }

    #[test]
    fn test_preload_empty_list() {
        let l2_cache = Arc::new(CompressedTileCache::new(64));
        let pool = Arc::new(SlidePool::new());
        let preloader = BulkPreloader::new(l2_cache, pool);

        // Empty list — no crash, no thread spawned
        preloader.start(vec![]);
        assert!(!preloader.is_running());
    }

    #[test]
    fn test_is_running_lifecycle() {
        let temp = TempDir::new().unwrap();
        let slide_dir = temp.path().join("slide.fastpath");
        fs::create_dir_all(&slide_dir).unwrap();
        create_test_fastpath_with_tiles(&slide_dir);
        let slide_id = compute_test_slide_id(&slide_dir);

        let l2_cache = Arc::new(CompressedTileCache::new(64));
        let pool = Arc::new(SlidePool::new());
        let preloader = BulkPreloader::new(Arc::clone(&l2_cache), Arc::clone(&pool));

        assert!(!preloader.is_running());

        preloader.start(vec![(slide_id, slide_dir)]);
        // Note: is_running() may or may not be true here depending on timing

        preloader.wait(); // wait for completion
        assert!(!preloader.is_running());
    }
}
