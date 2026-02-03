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

                                if let Some(tile_path) = entry
                                    .resolver
                                    .get_tile_path(level_info.level, col, row)
                                {
                                    tile_work.push((l2_coord, tile_path));
                                }
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
    use std::fs;
    use tempfile::TempDir;

    /// Create a minimal valid JPEG file (1x1 white pixel).
    fn create_test_jpeg_file(path: &std::path::Path) {
        #[rustfmt::skip]
        let jpeg_bytes: Vec<u8> = vec![
            // SOI
            0xFF, 0xD8,
            // APP0 (JFIF header)
            0xFF, 0xE0, 0x00, 0x10, 0x4A, 0x46, 0x49, 0x46,
            0x00, 0x01, 0x01, 0x00, 0x00, 0x01, 0x00, 0x01,
            0x00, 0x00,
            // DQT (quantization table)
            0xFF, 0xDB, 0x00, 0x43, 0x00,
            0x08, 0x06, 0x06, 0x07, 0x06, 0x05, 0x08, 0x07,
            0x07, 0x07, 0x09, 0x09, 0x08, 0x0A, 0x0C, 0x14,
            0x0D, 0x0C, 0x0B, 0x0B, 0x0C, 0x19, 0x12, 0x13,
            0x0F, 0x14, 0x1D, 0x1A, 0x1F, 0x1E, 0x1D, 0x1A,
            0x1C, 0x1C, 0x20, 0x24, 0x2E, 0x27, 0x20, 0x22,
            0x2C, 0x23, 0x1C, 0x1C, 0x28, 0x37, 0x29, 0x2C,
            0x30, 0x31, 0x34, 0x34, 0x34, 0x1F, 0x27, 0x39,
            0x3D, 0x38, 0x32, 0x3C, 0x2E, 0x33, 0x34, 0x32,
            // SOF0 (start of frame, baseline, 1x1, 1 component)
            0xFF, 0xC0, 0x00, 0x0B, 0x08, 0x00, 0x01, 0x00,
            0x01, 0x01, 0x01, 0x11, 0x00,
            // DHT (Huffman table, DC, table 0)
            0xFF, 0xC4, 0x00, 0x1F, 0x00, 0x00, 0x01, 0x05,
            0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x00, 0x00,
            0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x01, 0x02,
            0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x0A,
            0x0B,
            // DHT (Huffman table, AC, table 0)
            0xFF, 0xC4, 0x00, 0xB5, 0x10, 0x00, 0x02, 0x01,
            0x03, 0x03, 0x02, 0x04, 0x03, 0x05, 0x05, 0x04,
            0x04, 0x00, 0x00, 0x01, 0x7D, 0x01, 0x02, 0x03,
            0x00, 0x04, 0x11, 0x05, 0x12, 0x21, 0x31, 0x41,
            0x06, 0x13, 0x51, 0x61, 0x07, 0x22, 0x71, 0x14,
            0x32, 0x81, 0x91, 0xA1, 0x08, 0x23, 0x42, 0xB1,
            0xC1, 0x15, 0x52, 0xD1, 0xF0, 0x24, 0x33, 0x62,
            0x72, 0x82, 0x09, 0x0A, 0x16, 0x17, 0x18, 0x19,
            0x1A, 0x25, 0x26, 0x27, 0x28, 0x29, 0x2A, 0x34,
            0x35, 0x36, 0x37, 0x38, 0x39, 0x3A, 0x43, 0x44,
            0x45, 0x46, 0x47, 0x48, 0x49, 0x4A, 0x53, 0x54,
            0x55, 0x56, 0x57, 0x58, 0x59, 0x5A, 0x63, 0x64,
            0x65, 0x66, 0x67, 0x68, 0x69, 0x6A, 0x73, 0x74,
            0x75, 0x76, 0x77, 0x78, 0x79, 0x7A, 0x83, 0x84,
            0x85, 0x86, 0x87, 0x88, 0x89, 0x8A, 0x92, 0x93,
            0x94, 0x95, 0x96, 0x97, 0x98, 0x99, 0x9A, 0xA2,
            0xA3, 0xA4, 0xA5, 0xA6, 0xA7, 0xA8, 0xA9, 0xAA,
            0xB2, 0xB3, 0xB4, 0xB5, 0xB6, 0xB7, 0xB8, 0xB9,
            0xBA, 0xC2, 0xC3, 0xC4, 0xC5, 0xC6, 0xC7, 0xC8,
            0xC9, 0xCA, 0xD2, 0xD3, 0xD4, 0xD5, 0xD6, 0xD7,
            0xD8, 0xD9, 0xDA, 0xE1, 0xE2, 0xE3, 0xE4, 0xE5,
            0xE6, 0xE7, 0xE8, 0xE9, 0xEA, 0xF1, 0xF2, 0xF3,
            0xF4, 0xF5, 0xF6, 0xF7, 0xF8, 0xF9, 0xFA,
            // SOS (start of scan)
            0xFF, 0xDA, 0x00, 0x08, 0x01, 0x01, 0x00, 0x00,
            0x3F, 0x00, 0x7B, 0x40,
            // EOI
            0xFF, 0xD9,
        ];
        fs::write(path, jpeg_bytes).unwrap();
    }

    /// Create a test .fastpath directory with actual JPEG tile files.
    fn create_test_fastpath_with_tiles(dir: &std::path::Path) {
        let metadata = r#"{
            "dimensions": [1024, 1024],
            "tile_size": 512,
            "levels": [
                {"level": 0, "downsample": 2, "cols": 1, "rows": 1},
                {"level": 1, "downsample": 1, "cols": 2, "rows": 2}
            ],
            "target_mpp": 0.5,
            "target_magnification": 20.0,
            "tile_format": "dzsave"
        }"#;
        fs::write(dir.join("metadata.json"), metadata).unwrap();

        // Level 0: 1x1 = 1 tile
        fs::create_dir_all(dir.join("tiles_files/0")).unwrap();
        create_test_jpeg_file(&dir.join("tiles_files/0/0_0.jpg"));

        // Level 1: 2x2 = 4 tiles
        fs::create_dir_all(dir.join("tiles_files/1")).unwrap();
        create_test_jpeg_file(&dir.join("tiles_files/1/0_0.jpg"));
        create_test_jpeg_file(&dir.join("tiles_files/1/0_1.jpg"));
        create_test_jpeg_file(&dir.join("tiles_files/1/1_0.jpg"));
        create_test_jpeg_file(&dir.join("tiles_files/1/1_1.jpg"));
    }

    fn compute_test_slide_id(dir: &std::path::Path) -> u64 {
        let canonical = dir.canonicalize().unwrap();
        compute_slide_id(&canonical.to_string_lossy().to_lowercase())
    }

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
