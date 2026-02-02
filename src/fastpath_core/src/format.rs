//! Tile path resolution for .fastpath directories.

use std::path::{Path, PathBuf};

use serde::Deserialize;

use crate::error::TileResult;

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
        let metadata: SlideMetadata = serde_json::from_str(&content)?;
        Ok(metadata)
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
}
