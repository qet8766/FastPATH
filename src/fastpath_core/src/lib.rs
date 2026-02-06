//! FastPATH Core - High-performance tile scheduler for WSI viewing.
//!
//! This Rust extension provides:
//! - Concurrent tile cache using moka (TinyLFU eviction)
//! - Parallel I/O with rayon thread pool
//! - Viewport-based prefetching with velocity prediction
//! - Fast JPEG decoding

mod bulk_preload;
mod cache;
mod decoder;
mod error;
mod format;
mod pack;
mod prefetch;
mod scheduler;
mod slide_pool;
mod tile_buffer;
mod tile_reader;
#[cfg(test)]
pub(crate) mod test_utils;

use std::path::Path;

use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyDict};

use scheduler::TileScheduler;
use tile_buffer::TileBuffer;
use tile_reader::FastpathTileReader;

/// Python-exposed tile scheduler with two-level caching.
///
/// L1 cache holds decoded RGB tile data (fast, large).
/// L2 cache holds compressed JPEG bytes (persists across slide switches).
///
/// Usage:
/// ```python
/// from fastpath_core import RustTileScheduler
///
/// scheduler = RustTileScheduler(cache_size_mb=12288, l2_cache_size_mb=32768,
///                               prefetch_distance=3)
/// scheduler.load("/path/to/slide.fastpath")
///
/// # Get a tile (returns (bytes, width, height) or None)
/// tile = scheduler.get_tile(level=0, col=5, row=3)
///
/// # Update viewport for prefetching
/// scheduler.update_viewport(x=100, y=200, width=800, height=600,
///                          scale=0.5, velocity_x=10.0, velocity_y=0.0)
///
/// # Get cache statistics (includes L1 and L2 keys)
/// stats = scheduler.cache_stats()
/// print(f"L1 hits: {stats['hits']}, L2 tiles: {stats['l2_num_tiles']}")
///
/// scheduler.close()
/// ```
#[pyclass]
pub struct RustTileScheduler {
    inner: TileScheduler,
}

#[pymethods]
impl RustTileScheduler {
    /// Create a new tile scheduler.
    ///
    /// Args:
    ///     cache_size_mb: Maximum L1 cache size in megabytes (default: 4096 = 4GB).
    ///         Holds decoded RGB tile data.
    ///     l2_cache_size_mb: Maximum L2 cache size in megabytes (default: 32768 = 32GB).
    ///         Holds compressed JPEG bytes; persists across slide switches.
    ///     prefetch_distance: Number of tiles to prefetch ahead (default: 3)
    #[new]
    #[pyo3(signature = (cache_size_mb=4096, l2_cache_size_mb=32768, prefetch_distance=3))]
    fn new(cache_size_mb: usize, l2_cache_size_mb: usize, prefetch_distance: u32) -> Self {
        Self {
            inner: TileScheduler::new(cache_size_mb, l2_cache_size_mb, prefetch_distance),
        }
    }

    /// Load a .fastpath directory.
    ///
    /// Args:
    ///     path: Path to the .fastpath directory
    ///
    /// Returns:
    ///     True if loaded successfully
    ///
    /// Raises:
    ///     RuntimeError: If the path doesn't exist or metadata is invalid
    fn load(&self, path: &str) -> PyResult<bool> {
        self.inner.load(path)?;
        Ok(true)
    }

    /// Close the current slide and clear the cache.
    fn close(&self) {
        self.inner.close();
    }

    /// Get a tile as raw RGB bytes.
    ///
    /// Args:
    ///     level: Pyramid level (0 = highest resolution)
    ///     col: Column index
    ///     row: Row index
    ///
    /// Returns:
    ///     Tuple of (bytes, width, height) or None if tile doesn't exist
    fn get_tile<'py>(
        &self,
        py: Python<'py>,
        level: u32,
        col: u32,
        row: u32,
    ) -> Option<(Bound<'py, PyBytes>, u32, u32)> {
        self.inner.get_tile(level, col, row).map(|tile| {
            (PyBytes::new(py, &tile.data), tile.width, tile.height)
        })
    }

    /// Get a tile as a zero-copy buffer (Python buffer protocol).
    ///
    /// This avoids copying decoded RGB bytes into a Python `bytes` object.
    /// QImage (PySide6) can wrap the returned `TileBuffer` directly.
    ///
    /// Returns:
    ///     Tuple of (TileBuffer, width, height) or None if tile doesn't exist
    fn get_tile_buffer<'py>(
        &self,
        py: Python<'py>,
        level: u32,
        col: u32,
        row: u32,
    ) -> PyResult<Option<(Bound<'py, TileBuffer>, u32, u32)>> {
        let Some(tile) = self.inner.get_tile(level, col, row) else {
            return Ok(None);
        };
        let width = tile.width;
        let height = tile.height;
        let buf = Py::new(py, TileBuffer::new(tile.data))?;
        Ok(Some((buf.into_bound(py), width, height)))
    }

    /// Get a tile as raw JPEG bytes (compressed).
    ///
    /// This is useful for letting Qt decode tiles (`QImage.fromData(...)`) and
    /// reducing Python<->Rust transfer bandwidth.
    ///
    /// Returns:
    ///     JPEG bytes or None if tile doesn't exist.
    fn get_tile_jpeg<'py>(
        &self,
        py: Python<'py>,
        level: u32,
        col: u32,
        row: u32,
    ) -> Option<Bound<'py, PyBytes>> {
        self.inner
            .get_tile_jpeg(level, col, row)
            .map(|jpeg| PyBytes::new(py, jpeg.as_ref()))
    }

    /// Update the viewport and trigger prefetching.
    ///
    /// Call this whenever the viewport changes to enable intelligent prefetching
    /// based on pan direction and velocity.
    ///
    /// Args:
    ///     x: Viewport left edge in slide coordinates
    ///     y: Viewport top edge in slide coordinates
    ///     width: Viewport width in slide coordinates
    ///     height: Viewport height in slide coordinates
    ///     scale: Current zoom scale (1.0 = full resolution)
    ///     velocity_x: Horizontal pan velocity (pixels/second)
    ///     velocity_y: Vertical pan velocity (pixels/second)
    #[pyo3(signature = (x, y, width, height, scale, velocity_x=0.0, velocity_y=0.0))]
    #[allow(clippy::too_many_arguments)]
    fn update_viewport(
        &self,
        x: f64,
        y: f64,
        width: f64,
        height: f64,
        scale: f64,
        velocity_x: f64,
        velocity_y: f64,
    ) {
        self.inner
            .update_viewport(x, y, width, height, scale, velocity_x, velocity_y);
    }

    /// Pre-warm cache with low-resolution level tiles.
    ///
    /// Call after load() to ensure tiles are ready before first render.
    /// This blocks until tiles are loaded. Loads ALL tiles from the 3 lowest
    /// resolution levels, guaranteeing any initial zoom level has tiles ready.
    fn prefetch_low_res_levels(&self) {
        self.inner.prefetch_low_res_levels();
    }

    /// Get cache statistics for both L1 and L2 caches.
    ///
    /// Returns:
    ///     Dict with L1 keys: hits, misses, hit_ratio, size_bytes, num_tiles
    ///     and L2 keys: l2_hits, l2_misses, l2_hit_ratio, l2_size_bytes, l2_num_tiles
    fn cache_stats<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let stats = self.inner.cache_stats();
        let dict = PyDict::new(py);
        // L1 keys (backward-compatible)
        dict.set_item("hits", stats.l1.hits)?;
        dict.set_item("misses", stats.l1.misses)?;
        dict.set_item("hit_ratio", stats.l1.hit_ratio)?;
        dict.set_item("size_bytes", stats.l1.size_bytes)?;
        dict.set_item("num_tiles", stats.l1.num_tiles)?;
        // L2 keys
        dict.set_item("l2_hits", stats.l2.hits)?;
        dict.set_item("l2_misses", stats.l2.misses)?;
        dict.set_item("l2_hit_ratio", stats.l2.hit_ratio)?;
        dict.set_item("l2_size_bytes", stats.l2.size_bytes)?;
        dict.set_item("l2_num_tiles", stats.l2.num_tiles)?;
        Ok(dict)
    }

    /// Reset cache hit/miss counters to zero.
    fn reset_cache_stats(&self) {
        self.inner.reset_cache_stats();
    }

    /// Whether a slide is currently loaded.
    #[getter]
    fn is_loaded(&self) -> bool {
        self.inner.is_loaded()
    }

    /// Tile size in pixels.
    #[getter]
    fn tile_size(&self) -> u32 {
        self.inner.tile_size()
    }

    /// Number of pyramid levels.
    #[getter]
    fn num_levels(&self) -> usize {
        self.inner.num_levels()
    }

    /// Slide width at level 0.
    #[getter]
    fn width(&self) -> u32 {
        self.inner.dimensions().0
    }

    /// Slide height at level 0.
    #[getter]
    fn height(&self) -> u32 {
        self.inner.dimensions().1
    }

    /// Get slide metadata.
    ///
    /// Returns:
    ///     Dict with keys: width, height, tile_size, num_levels, mpp, magnification
    ///     or None if no slide is loaded
    fn get_metadata<'py>(&self, py: Python<'py>) -> PyResult<Option<Bound<'py, PyDict>>> {
        if let Some((w, h, tile_size, num_levels, mpp, mag)) = self.inner.get_metadata() {
            let dict = PyDict::new(py);
            dict.set_item("width", w)?;
            dict.set_item("height", h)?;
            dict.set_item("tile_size", tile_size)?;
            dict.set_item("num_levels", num_levels)?;
            dict.set_item("mpp", mpp)?;
            dict.set_item("magnification", mag)?;
            Ok(Some(dict))
        } else {
            Ok(None)
        }
    }

    /// Get level information.
    ///
    /// Args:
    ///     level: Level index
    ///
    /// Returns:
    ///     Tuple of (downsample, cols, rows) or None if level doesn't exist
    fn get_level_info(&self, level: u32) -> Option<(u32, u32, u32)> {
        self.inner.get_level_info(level)
    }

    /// Filter a list of tiles to only those that are cached.
    ///
    /// Args:
    ///     tiles: List of (level, col, row) tuples
    ///
    /// Returns:
    ///     List of (level, col, row) tuples that are in cache
    fn filter_cached_tiles(&self, tiles: Vec<(u32, u32, u32)>) -> Vec<(u32, u32, u32)> {
        self.inner.filter_cached_tiles(&tiles)
    }

    /// Start background preloading of directory slides into L2 cache.
    ///
    /// Args:
    ///     slide_paths: List of .fastpath directory paths in priority order
    ///         (current slide first, then alternating neighbors)
    fn start_bulk_preload(&self, slide_paths: Vec<String>) {
        self.inner.start_bulk_preload(slide_paths);
    }

    /// Cancel any running bulk preload operation.
    fn cancel_bulk_preload(&self) {
        self.inner.cancel_bulk_preload();
    }

    /// Whether a bulk preload is currently running.
    #[getter]
    fn is_bulk_preloading(&self) -> bool {
        self.inner.is_bulk_preloading()
    }
}

/// Pack dzsave output tiles_files into per-level tiles/level_N.pack + level_N.idx.
///
/// Args:
///   path: Path to the .fastpath directory (must contain tiles_files from dzsave)
///   levels: List of (level, cols, rows) entries
///   progress_cb: Optional callable(level_index, total_levels) called after each level
#[pyfunction]
#[pyo3(signature = (path, levels, progress_cb=None))]
fn pack_dzsave_tiles(
    py: Python<'_>,
    path: &str,
    levels: Vec<(u32, u32, u32)>,
    progress_cb: Option<PyObject>,
) -> PyResult<()> {
    let cb = progress_cb.map(|py_cb| -> Box<dyn Fn(u32, u32) + Send + Sync> {
        let py_cb = std::sync::Mutex::new(py_cb);
        Box::new(move |level_idx: u32, total_levels: u32| {
            let py_cb = py_cb.lock().unwrap();
            Python::with_gil(|py| {
                if let Err(e) = py_cb.call1(py, (level_idx, total_levels)) {
                    eprintln!("[PACK] Progress callback error: {e}");
                }
            });
        })
    });

    py.allow_threads(|| pack::pack_dzsave_tiles(Path::new(path), &levels, cb))?;
    Ok(())
}

/// Benchmark: old sequential + per-tile stat packing (no cleanup).
#[pyfunction]
fn bench_pack_seq_stat(py: Python<'_>, path: &str, levels: Vec<(u32, u32, u32)>) -> PyResult<()> {
    py.allow_threads(|| pack::pack_dzsave_tiles_bench_seq_stat(Path::new(path), &levels))?;
    Ok(())
}

/// Benchmark: sequential + directory prescan packing (no cleanup).
#[pyfunction]
fn bench_pack_seq_prescan(
    py: Python<'_>,
    path: &str,
    levels: Vec<(u32, u32, u32)>,
) -> PyResult<()> {
    py.allow_threads(|| pack::pack_dzsave_tiles_bench_seq_prescan(Path::new(path), &levels))?;
    Ok(())
}

/// Benchmark: parallel + prescan packing (no cleanup).
#[pyfunction]
fn bench_pack_parallel(
    py: Python<'_>,
    path: &str,
    levels: Vec<(u32, u32, u32)>,
) -> PyResult<()> {
    py.allow_threads(|| pack::pack_dzsave_tiles_bench_parallel(Path::new(path), &levels))?;
    Ok(())
}

/// Whether the Rust extension was compiled without optimizations (debug build).
#[pyfunction]
fn is_debug_build() -> bool {
    cfg!(debug_assertions)
}

/// FastPATH Core - High-performance tile scheduler for WSI viewing.
#[pymodule]
fn fastpath_core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<RustTileScheduler>()?;
    m.add_class::<TileBuffer>()?;
    m.add_class::<FastpathTileReader>()?;
    m.add_function(wrap_pyfunction!(pack_dzsave_tiles, m)?)?;
    m.add_function(wrap_pyfunction!(bench_pack_seq_stat, m)?)?;
    m.add_function(wrap_pyfunction!(bench_pack_seq_prescan, m)?)?;
    m.add_function(wrap_pyfunction!(bench_pack_parallel, m)?)?;
    m.add_function(wrap_pyfunction!(is_debug_build, m)?)?;
    Ok(())
}
