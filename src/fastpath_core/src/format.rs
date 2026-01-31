//! Tile path resolution for different .fastpath formats.

use std::path::{Path, PathBuf};

use serde::Deserialize;

use crate::error::TileResult;

/// Tile format type.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum TileFormat {
    /// Traditional format: levels/N/col_row.jpg
    #[default]
    Traditional,
    /// DZSave format: tiles_files/N/col_row.jpg
    DzSave,
}

impl TileFormat {
    pub fn from_str(s: &str) -> Self {
        match s {
            "dzsave" => TileFormat::DzSave,
            _ => TileFormat::Traditional,
        }
    }
}

/// Information about a pyramid level.
#[derive(Debug, Clone, Deserialize)]
pub struct LevelInfo {
    pub level: u32,
    pub downsample: u32,
    pub cols: u32,
    pub rows: u32,
}

/// Metadata from metadata.json.
#[derive(Debug, Clone, Deserialize)]
pub struct SlideMetadata {
    pub dimensions: (u32, u32),
    pub tile_size: u32,
    pub levels: Vec<LevelInfo>,
    pub target_mpp: f64,
    pub target_magnification: f64,
    #[serde(default)]
    pub tile_format: String,
    #[serde(default)]
    pub source_file: String,
}

impl SlideMetadata {
    /// Load metadata from a .fastpath directory.
    pub fn load(fastpath_dir: &Path) -> TileResult<Self> {
        let metadata_path = fastpath_dir.join("metadata.json");
        let content = std::fs::read_to_string(&metadata_path)?;
        let metadata: SlideMetadata = serde_json::from_str(&content)?;
        Ok(metadata)
    }

    /// Get the tile format.
    pub fn format(&self) -> TileFormat {
        TileFormat::from_str(&self.tile_format)
    }

    /// Get level info by level number.
    pub fn get_level(&self, level: u32) -> Option<&LevelInfo> {
        self.levels.iter().find(|l| l.level == level)
    }

    /// Get total number of levels.
    pub fn num_levels(&self) -> usize {
        self.levels.len()
    }
}

/// Resolves tile paths for a loaded slide.
#[derive(Debug, Clone)]
pub struct TilePathResolver {
    fastpath_dir: PathBuf,
    format: TileFormat,
}

impl TilePathResolver {
    /// Create a new resolver for a .fastpath directory.
    pub fn new(fastpath_dir: PathBuf, metadata: &SlideMetadata) -> TileResult<Self> {
        let format = metadata.format();

        Ok(Self {
            fastpath_dir,
            format,
        })
    }

    /// Get the file path for a tile.
    ///
    /// Args:
    ///     level: Pyramid level number
    ///     col: Column index
    ///     row: Row index
    ///
    /// Returns:
    ///     Path to the tile file if it exists.
    pub fn get_tile_path(&self, level: u32, col: u32, row: u32) -> Option<PathBuf> {
        let path = match self.format {
            TileFormat::Traditional => {
                // levels/N/col_row.jpg
                self.fastpath_dir
                    .join("levels")
                    .join(level.to_string())
                    .join(format!("{}_{}.jpg", col, row))
            }
            TileFormat::DzSave => {
                // Level number matches dzsave directory name directly
                self.fastpath_dir
                    .join("tiles_files")
                    .join(level.to_string())
                    .join(format!("{}_{}.jpg", col, row))
            }
        };

        // Return path directly - decode_tile() handles missing files
        Some(path)
    }

    /// Get the format being used.
    pub fn format(&self) -> TileFormat {
        self.format
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use tempfile::TempDir;

    fn create_test_metadata() -> SlideMetadata {
        SlideMetadata {
            dimensions: (10000, 10000),
            tile_size: 512,
            levels: vec![
                LevelInfo {
                    level: 0,
                    downsample: 1,
                    cols: 20,
                    rows: 20,
                },
                LevelInfo {
                    level: 1,
                    downsample: 2,
                    cols: 10,
                    rows: 10,
                },
            ],
            target_mpp: 0.5,
            target_magnification: 20.0,
            tile_format: "traditional".to_string(),
            source_file: "test.svs".to_string(),
        }
    }

    #[test]
    fn test_traditional_format_path() {
        let temp = TempDir::new().unwrap();
        let dir = temp.path();

        // Create structure with .jpg
        fs::create_dir_all(dir.join("levels/0")).unwrap();
        fs::write(dir.join("levels/0/5_3.jpg"), b"fake").unwrap();

        let metadata = create_test_metadata();
        let resolver = TilePathResolver::new(dir.to_path_buf(), &metadata).unwrap();

        let path = resolver.get_tile_path(0, 5, 3);
        assert!(path.is_some());
        assert!(path.unwrap().ends_with("levels/0/5_3.jpg"));
    }

    #[test]
    fn test_missing_tile_returns_path() {
        // get_tile_path now returns the path regardless of existence
        // decode_tile() handles missing files gracefully
        let temp = TempDir::new().unwrap();
        let dir = temp.path();

        fs::create_dir_all(dir.join("levels/0")).unwrap();

        let metadata = create_test_metadata();
        let resolver = TilePathResolver::new(dir.to_path_buf(), &metadata).unwrap();

        let path = resolver.get_tile_path(0, 99, 99);
        assert!(path.is_some());
        assert!(path.unwrap().ends_with("levels/0/99_99.jpg"));
    }
}
