//! FastPATH Core - High-performance tile scheduler for WSI viewing.
//!
//! This Rust extension provides:
//! - Concurrent tile cache using moka (TinyLFU eviction)
//! - Parallel I/O with rayon thread pool
//! - Viewport-based prefetching with velocity prediction
//! - Fast JPEG decoding

mod cache;
mod decoder;
mod error;
mod format;
mod prefetch;
mod scheduler;

use pyo3::prelude::*;
use pyo3::types::PyDict;

use scheduler::TileScheduler;

/// Python-exposed tile scheduler.
///
/// Usage:
/// ```python
/// from fastpath_core import RustTileScheduler
///
/// scheduler = RustTileScheduler(cache_size_mb=12288, prefetch_distance=3)
/// scheduler.load("/path/to/slide.fastpath")
///
/// # Get a tile (returns (bytes, width, height) or None)
/// tile = scheduler.get_tile(level=0, col=5, row=3)
///
/// # Update viewport for prefetching
/// scheduler.update_viewport(x=100, y=200, width=800, height=600,
///                          scale=0.5, velocity_x=10.0, velocity_y=0.0)
///
/// # Get cache statistics
/// stats = scheduler.cache_stats()
/// print(f"Cache hits: {stats['hits']}, misses: {stats['misses']}")
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
    ///     cache_size_mb: Maximum cache size in megabytes (default: 12288 = 12GB)
    ///     prefetch_distance: Number of tiles to prefetch ahead (default: 3)
    #[new]
    #[pyo3(signature = (cache_size_mb=12288, prefetch_distance=3))]
    fn new(cache_size_mb: usize, prefetch_distance: u32) -> Self {
        Self {
            inner: TileScheduler::new(cache_size_mb, prefetch_distance),
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
    fn get_tile(&self, level: u32, col: u32, row: u32) -> Option<(Vec<u8>, u32, u32)> {
        self.inner.get_tile(level, col, row).map(|tile| {
            (tile.data.to_vec(), tile.width, tile.height)
        })
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

    /// Get cache statistics.
    ///
    /// Returns:
    ///     Dict with keys: hits, misses, size_bytes, num_tiles
    fn cache_stats<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let stats = self.inner.cache_stats();
        let dict = PyDict::new(py);
        dict.set_item("hits", stats.hits)?;
        dict.set_item("misses", stats.misses)?;
        dict.set_item("size_bytes", stats.size_bytes)?;
        dict.set_item("num_tiles", stats.num_tiles)?;
        Ok(dict)
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
}

/// FastPATH Core - High-performance tile scheduler for WSI viewing.
#[pymodule]
fn fastpath_core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<RustTileScheduler>()?;
    Ok(())
}
