//! Plugin-facing tile decoding helpers.
//!
//! These APIs provide high-performance tile decoding and region assembly for plugins,
//! avoiding Python-level loops and libvips/PIL decoding when possible.

use std::path::PathBuf;

use bytes::Bytes;
use pyo3::prelude::*;
use pyo3::types::PyBytes;

use crate::decoder::{decode_jpeg_bytes, CompressedTileData};
use crate::format::SlideMetadata;
use crate::pack::TilePack;

#[pyclass]
pub struct FastpathTileReader {
    metadata: SlideMetadata,
    pack: TilePack,
}

fn div_floor(a: i64, b: i64) -> i64 {
    a.div_euclid(b)
}

fn decode_tile_bytes(pack: &TilePack, level: u32, col: u32, row: u32) -> crate::error::TileResult<Option<(Bytes, u32, u32)>> {
    let tile_ref = match pack.tile_ref(level, col, row) {
        Some(r) => r,
        None => return Ok(None),
    };

    let jpeg_bytes = pack.read_tile_bytes(tile_ref)?;
    let compressed = CompressedTileData {
        jpeg_bytes,
        width: 0,
        height: 0,
    };
    let tile = decode_jpeg_bytes(&compressed)?;
    Ok(Some((tile.data, tile.width, tile.height)))
}

fn decode_region_bytes(
    pack: &TilePack,
    tile_size: i64,
    level: u32,
    x: i64,
    y: i64,
    w: u32,
    h: u32,
) -> crate::error::TileResult<Vec<u8>> {
    if w == 0 || h == 0 {
        return Err(crate::error::TileError::Validation(
            "Region width and height must be positive".into(),
        ));
    }
    if tile_size <= 0 {
        return Err(crate::error::TileError::Validation(
            "tile_size must be positive".into(),
        ));
    }

    let out_w = w as usize;
    let out_h = h as usize;
    let out_len = out_w
        .checked_mul(out_h)
        .and_then(|n| n.checked_mul(3))
        .ok_or_else(|| {
            crate::error::TileError::Validation("Requested region is too large".into())
        })?;

    let mut out = vec![255u8; out_len];

    let x2 = x
        .checked_add(w as i64)
        .ok_or_else(|| crate::error::TileError::Validation("x+w overflow".into()))?;
    let y2 = y
        .checked_add(h as i64)
        .ok_or_else(|| crate::error::TileError::Validation("y+h overflow".into()))?;

    let col_start = div_floor(x, tile_size);
    let col_end = div_floor(x2 - 1, tile_size) + 1;
    let row_start = div_floor(y, tile_size);
    let row_end = div_floor(y2 - 1, tile_size) + 1;

    for r in row_start..row_end {
        for c in col_start..col_end {
            if c < 0 || r < 0 {
                continue;
            }

            let Some((tile_bytes, tile_w_u32, tile_h_u32)) =
                decode_tile_bytes(pack, level, c as u32, r as u32)?
            else {
                continue;
            };

            let tile_w = tile_w_u32 as i64;
            let tile_h = tile_h_u32 as i64;
            if tile_w <= 0 || tile_h <= 0 {
                continue;
            }

            let tile_x = c
                .checked_mul(tile_size)
                .ok_or_else(|| crate::error::TileError::Validation("tile_x overflow".into()))?;
            let tile_y = r
                .checked_mul(tile_size)
                .ok_or_else(|| crate::error::TileError::Validation("tile_y overflow".into()))?;

            // Intersection in level coordinates.
            let left = x.max(tile_x);
            let top = y.max(tile_y);
            let right = x2.min(tile_x + tile_w);
            let bottom = y2.min(tile_y + tile_h);

            if left >= right || top >= bottom {
                continue;
            }

            let copy_w = (right - left) as usize;
            let copy_h = (bottom - top) as usize;
            let src_x = (left - tile_x) as usize;
            let src_y = (top - tile_y) as usize;
            let dst_x = (left - x) as usize;
            let dst_y = (top - y) as usize;

            let tile_w_usize: usize = tile_w_u32 as usize;

            for row in 0..copy_h {
                let src_row_start = ((src_y + row) * tile_w_usize + src_x) * 3;
                let dst_row_start = ((dst_y + row) * out_w + dst_x) * 3;
                let byte_len = copy_w * 3;
                out[dst_row_start..dst_row_start + byte_len]
                    .copy_from_slice(&tile_bytes[src_row_start..src_row_start + byte_len]);
            }
        }
    }

    Ok(out)
}

#[pymethods]
impl FastpathTileReader {
    #[new]
    fn new(path: &str) -> PyResult<Self> {
        let path_buf = PathBuf::from(path);
        let metadata = SlideMetadata::load(&path_buf)?;
        let pack = TilePack::open(&path_buf)?;
        Ok(Self { metadata, pack })
    }

    /// Tile size in pixels.
    #[getter]
    fn tile_size(&self) -> u32 {
        self.metadata.tile_size
    }

    /// Decode a single tile to raw RGB bytes.
    ///
    /// Returns (bytes, width, height) or None if missing/out-of-bounds.
    fn decode_tile<'py>(
        &self,
        py: Python<'py>,
        level: u32,
        col: u32,
        row: u32,
    ) -> PyResult<Option<(Bound<'py, PyBytes>, u32, u32)>> {
        let decoded = py.allow_threads(|| decode_tile_bytes(&self.pack, level, col, row));
        match decoded? {
            Some((data, w, h)) => Ok(Some((PyBytes::new(py, &data), w, h))),
            None => Ok(None),
        }
    }

    /// Decode a region (level coordinates) to raw RGB bytes.
    ///
    /// Args:
    ///   level: Pyramid level number.
    ///   x, y: Top-left in level pixels (may be negative).
    ///   w, h: Region size in pixels (must be positive).
    ///
    /// Returns:
    ///   bytes of length w*h*3 in row-major RGB order.
    fn decode_region<'py>(
        &self,
        py: Python<'py>,
        level: u32,
        x: i64,
        y: i64,
        w: u32,
        h: u32,
    ) -> PyResult<Bound<'py, PyBytes>> {
        let tile_size = self.metadata.tile_size as i64;
        let data = py.allow_threads(|| decode_region_bytes(&self.pack, tile_size, level, x, y, w, h))?;
        Ok(PyBytes::new(py, &data))
    }
}

