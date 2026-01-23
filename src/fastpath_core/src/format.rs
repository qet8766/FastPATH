//! Tile path resolution for different .fastpath formats.

use std::path::{Path, PathBuf};

use serde::Deserialize;

use crate::error::{TileError, TileResult};

/// Tile format type.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum TileFormat {
    /// Traditional format: levels/N/col_row.jpg
    #[default]
    Traditional,
    /// DZSave format: tiles_files/N/col_row.jpg (inverted levels)
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

    /// Get level info by index.
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
    max_dz_level: u32,
}

impl TilePathResolver {
    /// Create a new resolver for a .fastpath directory.
    pub fn new(fastpath_dir: PathBuf, metadata: &SlideMetadata) -> TileResult<Self> {
        let format = metadata.format();
        let max_dz_level = if format == TileFormat::DzSave {
            Self::detect_max_dz_level(&fastpath_dir)?
        } else {
            0
        };

        Ok(Self {
            fastpath_dir,
            format,
            max_dz_level,
        })
    }

    /// Detect the maximum dzsave level by scanning the directory.
    fn detect_max_dz_level(fastpath_dir: &Path) -> TileResult<u32> {
        let tiles_dir = fastpath_dir.join("tiles_files");
        if !tiles_dir.exists() {
            return Err(TileError::MetadataError(
                "tiles_files directory not found for dzsave format".to_string(),
            ));
        }

        let mut max_level = 0u32;
        for entry in std::fs::read_dir(&tiles_dir)? {
            let entry = entry?;
            if entry.file_type()?.is_dir() {
                if let Some(name) = entry.file_name().to_str() {
                    if let Ok(level) = name.parse::<u32>() {
                        max_level = max_level.max(level);
                    }
                }
            }
        }

        Ok(max_level)
    }

    /// Get the file path for a tile.
    ///
    /// Args:
    ///     level: FastPATH pyramid level (0 = highest resolution)
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
                // dzsave levels are inverted: 0 = lowest resolution, max = highest
                // FastPATH level 0 = highest resolution = dzsave max level
                let dz_level = self.max_dz_level.saturating_sub(level);
                self.fastpath_dir
                    .join("tiles_files")
                    .join(dz_level.to_string())
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
