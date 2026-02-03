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

/// Compressed JPEG tile data (not yet decoded to RGB).
#[derive(Debug, Clone)]
pub struct CompressedTileData {
    /// Raw JPEG file bytes.
    pub jpeg_bytes: Bytes,
    /// Tile width in pixels (parsed from JPEG header).
    /// Used by L2 cache reads (Part 4).
    #[allow(dead_code)]
    pub width: u32,
    /// Tile height in pixels (parsed from JPEG header).
    /// Used by L2 cache reads (Part 4).
    #[allow(dead_code)]
    pub height: u32,
}

impl CompressedTileData {
    /// Size in bytes (JPEG compressed size, used for cache weighting).
    pub fn size_bytes(&self) -> usize {
        self.jpeg_bytes.len()
    }
}

/// Read a JPEG tile file and parse its header for dimensions.
///
/// Returns compressed JPEG bytes with width/height metadata.
/// Does NOT decode pixels — use `decode_jpeg_bytes()` for that.
pub fn read_jpeg_bytes(path: &Path) -> TileResult<CompressedTileData> {
    let mut file = File::open(path)?;
    let mut jpeg_data = Vec::new();
    file.read_to_end(&mut jpeg_data)?;

    // Parse JPEG header for dimensions without decoding pixels
    let mut decoder = JpegDecoder::new(&jpeg_data);
    decoder
        .decode_headers()
        .map_err(|e| TileError::Decode(format!("Failed to parse JPEG header: {:?}", e)))?;

    let info = decoder
        .info()
        .ok_or_else(|| TileError::Decode("Failed to get image info from header".into()))?;

    Ok(CompressedTileData {
        jpeg_bytes: Bytes::from(jpeg_data),
        width: info.width as u32,
        height: info.height as u32,
    })
}

/// Decode compressed JPEG bytes to RGB pixel data.
///
/// Handles grayscale-to-RGB conversion automatically.
pub fn decode_jpeg_bytes(compressed: &CompressedTileData) -> TileResult<TileData> {
    let mut decoder = JpegDecoder::new(compressed.jpeg_bytes.as_ref());

    let pixels = decoder
        .decode()
        .map_err(|e| TileError::Decode(format!("Failed to decode JPEG: {:?}", e)))?;

    let info = decoder
        .info()
        .ok_or_else(|| TileError::Decode("Failed to get image info".into()))?;

    let width = info.width as u32;
    let height = info.height as u32;

    let rgb_data = if info.components == 1 {
        pixels.iter().flat_map(|&gray| [gray, gray, gray]).collect()
    } else {
        pixels
    };

    Ok(TileData::new(rgb_data, width, height))
}

/// Decode a tile from a file path.
///
/// Supports JPEG (.jpg, .jpeg) format.
/// Uses zune-jpeg for fast SIMD-accelerated decoding.
/// Convenience wrapper used by tests; scheduler uses split read/decode path.
#[allow(dead_code)]
pub fn decode_tile(path: &Path) -> TileResult<TileData> {
    let compressed = read_jpeg_bytes(path)?;
    decode_jpeg_bytes(&compressed)
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

    #[test]
    fn test_read_jpeg_bytes_invalid_path() {
        let result = read_jpeg_bytes(Path::new("/nonexistent/path.jpg"));
        assert!(result.is_err());
    }

    #[test]
    fn test_read_jpeg_bytes_invalid_data() {
        let temp = TempDir::new().unwrap();
        let path = temp.path().join("fake.jpg");
        fs::write(&path, b"not a jpeg").unwrap();
        let result = read_jpeg_bytes(&path);
        assert!(result.is_err());
    }

    #[test]
    fn test_compressed_tile_data_size() {
        let data = CompressedTileData {
            jpeg_bytes: Bytes::from(vec![0u8; 1024]),
            width: 512,
            height: 512,
        };
        assert_eq!(data.size_bytes(), 1024);
    }

    #[test]
    fn test_decode_jpeg_bytes_invalid_data() {
        let bad = CompressedTileData {
            jpeg_bytes: Bytes::from(b"not a jpeg".to_vec()),
            width: 0,
            height: 0,
        };
        let result = decode_jpeg_bytes(&bad);
        assert!(result.is_err());
    }
}
