//! Tile path resolution for .fastpath directories.

use std::path::{Path, PathBuf};

use serde::Deserialize;

use crate::error::{TileError, TileResult};

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
}

impl SlideMetadata {
    /// Load metadata from a .fastpath directory.
    pub fn load(fastpath_dir: &Path) -> TileResult<Self> {
        let metadata_path = fastpath_dir.join("metadata.json");
        let content = std::fs::read_to_string(&metadata_path)?;
        let mut metadata: SlideMetadata = serde_json::from_str(&content)?;
        metadata.validate()?;
        Ok(metadata)
    }

    /// Validate metadata fields and sort levels by level number.
    fn validate(&mut self) -> TileResult<()> {
        if self.dimensions.0 == 0 || self.dimensions.1 == 0 {
            return Err(TileError::Validation(
                "dimensions must be positive".into(),
            ));
        }
        if self.tile_size == 0 {
            return Err(TileError::Validation(
                "tile_size must be positive".into(),
            ));
        }
        if self.levels.is_empty() {
            return Err(TileError::Validation(
                "levels must not be empty".into(),
            ));
        }
        self.levels.sort_by_key(|l| l.level);
        for (i, li) in self.levels.iter().enumerate() {
            if li.downsample == 0 {
                return Err(TileError::Validation(
                    format!("level {}: downsample must be positive", li.level),
                ));
            }
            if li.cols == 0 {
                return Err(TileError::Validation(
                    format!("level {}: cols must be positive", li.level),
                ));
            }
            if li.rows == 0 {
                return Err(TileError::Validation(
                    format!("level {}: rows must be positive", li.level),
                ));
            }
            if i > 0 && li.level == self.levels[i - 1].level {
                return Err(TileError::Validation(
                    format!("duplicate level number: {}", li.level),
                ));
            }
        }
        Ok(())
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
}

impl TilePathResolver {
    /// Create a new resolver for a .fastpath directory.
    pub fn new(fastpath_dir: PathBuf) -> TileResult<Self> {
        Ok(Self { fastpath_dir })
    }

    /// Get the file path for a tile.
    ///
    /// Args:
    ///     level: Pyramid level number
    ///     col: Column index
    ///     row: Row index
    ///
    /// Returns:
    ///     Path to the tile file.
    pub fn get_tile_path(&self, level: u32, col: u32, row: u32) -> Option<PathBuf> {
        let path = self.fastpath_dir
            .join("tiles_files")
            .join(level.to_string())
            .join(format!("{}_{}.jpg", col, row));

        // Return path directly - decode_tile() handles missing files
        Some(path)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use tempfile::TempDir;

    /// Build a valid SlideMetadata for testing. Tests can mutate fields before calling validate().
    fn valid_metadata() -> SlideMetadata {
        SlideMetadata {
            dimensions: (1000, 2000),
            tile_size: 512,
            levels: vec![
                LevelInfo { level: 0, downsample: 8, cols: 1, rows: 1 },
                LevelInfo { level: 1, downsample: 4, cols: 2, rows: 4 },
                LevelInfo { level: 2, downsample: 1, cols: 4, rows: 8 },
            ],
            target_mpp: 0.5,
            target_magnification: 20.0,
        }
    }

    /// Write metadata JSON to a temp dir and load it via SlideMetadata::load().
    fn write_and_load(dir: &Path, json: &str) -> TileResult<SlideMetadata> {
        fs::write(dir.join("metadata.json"), json).unwrap();
        SlideMetadata::load(dir)
    }

    #[test]
    fn test_dzsave_format_path() {
        let temp = TempDir::new().unwrap();
        let dir = temp.path();

        fs::create_dir_all(dir.join("tiles_files/0")).unwrap();
        fs::write(dir.join("tiles_files/0/5_3.jpg"), b"fake").unwrap();

        let resolver = TilePathResolver::new(dir.to_path_buf()).unwrap();

        let path = resolver.get_tile_path(0, 5, 3);
        assert!(path.is_some());
        assert!(path.unwrap().ends_with("tiles_files/0/5_3.jpg"));
    }

    #[test]
    fn test_missing_tile_returns_path() {
        // get_tile_path now returns the path regardless of existence
        // decode_tile() handles missing files gracefully
        let temp = TempDir::new().unwrap();
        let dir = temp.path();

        fs::create_dir_all(dir.join("tiles_files/0")).unwrap();

        let resolver = TilePathResolver::new(dir.to_path_buf()).unwrap();

        let path = resolver.get_tile_path(0, 99, 99);
        assert!(path.is_some());
        assert!(path.unwrap().ends_with("tiles_files/0/99_99.jpg"));
    }

    #[test]
    fn test_load_valid_metadata() {
        let temp = TempDir::new().unwrap();
        let json = r#"{
            "dimensions": [1000, 2000],
            "tile_size": 512,
            "levels": [
                {"level": 0, "downsample": 8, "cols": 1, "rows": 1},
                {"level": 1, "downsample": 4, "cols": 2, "rows": 4},
                {"level": 2, "downsample": 1, "cols": 4, "rows": 8}
            ],
            "target_mpp": 0.5,
            "target_magnification": 20.0
        }"#;
        let metadata = write_and_load(temp.path(), json).unwrap();
        assert_eq!(metadata.dimensions, (1000, 2000));
        assert_eq!(metadata.num_levels(), 3);
    }

    #[test]
    fn test_validate_empty_levels() {
        let mut m = valid_metadata();
        m.levels.clear();
        let err = m.validate().unwrap_err();
        assert!(err.to_string().contains("levels must not be empty"));
    }

    #[test]
    fn test_validate_zero_tile_size() {
        let mut m = valid_metadata();
        m.tile_size = 0;
        let err = m.validate().unwrap_err();
        assert!(err.to_string().contains("tile_size must be positive"));
    }

    #[test]
    fn test_validate_zero_dimensions() {
        let mut m = valid_metadata();
        m.dimensions = (0, 1000);
        let err = m.validate().unwrap_err();
        assert!(err.to_string().contains("dimensions must be positive"));

        let mut m = valid_metadata();
        m.dimensions = (1000, 0);
        let err = m.validate().unwrap_err();
        assert!(err.to_string().contains("dimensions must be positive"));
    }

    #[test]
    fn test_validate_zero_downsample() {
        let mut m = valid_metadata();
        m.levels[1].downsample = 0;
        let err = m.validate().unwrap_err();
        assert!(err.to_string().contains("level 1: downsample must be positive"));
    }

    #[test]
    fn test_validate_zero_cols() {
        let mut m = valid_metadata();
        m.levels[2].cols = 0;
        let err = m.validate().unwrap_err();
        assert!(err.to_string().contains("level 2: cols must be positive"));
    }

    #[test]
    fn test_validate_zero_rows() {
        let mut m = valid_metadata();
        m.levels[0].rows = 0;
        let err = m.validate().unwrap_err();
        assert!(err.to_string().contains("level 0: rows must be positive"));
    }

    #[test]
    fn test_validate_duplicate_levels() {
        let mut m = valid_metadata();
        m.levels[2].level = 1; // duplicate of levels[1]
        let err = m.validate().unwrap_err();
        assert!(err.to_string().contains("duplicate level number: 1"));
    }

    #[test]
    fn test_validate_sorts_levels() {
        let mut m = SlideMetadata {
            dimensions: (1000, 2000),
            tile_size: 512,
            levels: vec![
                LevelInfo { level: 2, downsample: 1, cols: 4, rows: 8 },
                LevelInfo { level: 0, downsample: 8, cols: 1, rows: 1 },
                LevelInfo { level: 1, downsample: 4, cols: 2, rows: 4 },
            ],
            target_mpp: 0.5,
            target_magnification: 20.0,
        };
        m.validate().unwrap();
        let level_nums: Vec<u32> = m.levels.iter().map(|l| l.level).collect();
        assert_eq!(level_nums, vec![0, 1, 2]);
    }
}
