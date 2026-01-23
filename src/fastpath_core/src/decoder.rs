//! Tile decoding for JPEG format.
//!
//! Uses zune-jpeg for fast SIMD-accelerated decoding (~2-3x faster than image crate).

use std::fs::File;
use std::io::Read;
use std::path::Path;

use bytes::Bytes;
use zune_jpeg::JpegDecoder;

use crate::error::{TileError, TileResult};

/// Decoded tile data.
#[derive(Debug, Clone)]
pub struct TileData {
    /// Raw RGB pixel data.
    pub data: Bytes,
    /// Tile width in pixels.
    pub width: u32,
    /// Tile height in pixels.
    pub height: u32,
}

impl TileData {
    /// Create new tile data.
    pub fn new(data: Vec<u8>, width: u32, height: u32) -> Self {
        Self {
            data: Bytes::from(data),
            width,
            height,
        }
    }

    /// Size in bytes.
    pub fn size_bytes(&self) -> usize {
        self.data.len()
    }
}

/// Decode a tile from a file path.
///
/// Supports JPEG (.jpg, .jpeg) format.
/// Uses zune-jpeg for fast SIMD-accelerated decoding.
pub fn decode_tile(path: &Path) -> TileResult<TileData> {
    // Read file into memory
    let mut file = File::open(path)?;
    let mut jpeg_data = Vec::new();
    file.read_to_end(&mut jpeg_data)?;

    // Create decoder and decode
    let mut decoder = JpegDecoder::new(&jpeg_data);

    let pixels = decoder
        .decode()
        .map_err(|e| TileError::DecodeError(format!("Failed to decode JPEG: {:?}", e)))?;

    let info = decoder
        .info()
        .ok_or_else(|| TileError::DecodeError("Failed to get image info".to_string()))?;

    let width = info.width as u32;
    let height = info.height as u32;

    // zune-jpeg outputs RGB by default for color images, grayscale for grayscale
    // Convert grayscale to RGB if needed
    let rgb_data = if info.components == 1 {
        // Grayscale -> RGB
        let mut rgb = Vec::with_capacity(pixels.len() * 3);
        for &gray in &pixels {
            rgb.push(gray);
            rgb.push(gray);
            rgb.push(gray);
        }
        rgb
    } else {
        pixels
    };

    Ok(TileData::new(rgb_data, width, height))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use tempfile::TempDir;

    #[test]
    fn test_decode_invalid_path() {
        let result = decode_tile(Path::new("/nonexistent/path.jpg"));
        assert!(result.is_err());
    }

    #[test]
    fn test_decode_invalid_jpeg() {
        let temp = TempDir::new().unwrap();
        let path = temp.path().join("fake.jpg");
        fs::write(&path, b"not a jpeg").unwrap();

        let result = decode_tile(&path);
        assert!(result.is_err());
    }
}
