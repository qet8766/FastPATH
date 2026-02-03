//! Metadata pool for .fastpath directories.
//!
//! Caches `SlideEntry` (metadata + path resolver) by slide_id so that
//! revisiting a slide with a warm L2 cache skips re-parsing metadata.json.

use std::collections::HashMap;
use std::path::Path;
use std::sync::Arc;

use parking_lot::RwLock;

use crate::error::TileResult;
use crate::format::{SlideMetadata, TilePathResolver};

/// Cached slide state: metadata + tile path resolver.
pub struct SlideEntry {
    pub metadata: SlideMetadata,
    pub resolver: TilePathResolver,
}

/// Pool of loaded slide metadata, keyed by slide_id hash.
///
/// Entries persist for the application lifetime. Memory overhead is
/// negligible (~300 bytes per slide) compared to tile data.
pub struct SlidePool {
    entries: RwLock<HashMap<u64, Arc<SlideEntry>>>,
}

impl SlidePool {
    pub fn new() -> Self {
        Self {
            entries: RwLock::new(HashMap::new()),
        }
    }

    /// Get a cached entry or load from disk.
    pub fn load_or_get(&self, slide_id: u64, fastpath_dir: &Path) -> TileResult<Arc<SlideEntry>> {
        // Fast path: already cached
        if let Some(entry) = self.entries.read().get(&slide_id) {
            return Ok(Arc::clone(entry));
        }

        // Slow path: load from disk
        let metadata = SlideMetadata::load(fastpath_dir)?;
        let resolver = TilePathResolver::new(fastpath_dir.to_path_buf());
        let entry = Arc::new(SlideEntry { metadata, resolver });

        self.entries.write().insert(slide_id, Arc::clone(&entry));
        Ok(entry)
    }

    /// Number of cached entries (for testing/diagnostics).
    #[cfg(test)]
    pub fn len(&self) -> usize {
        self.entries.read().len()
    }
}

impl Default for SlidePool {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::test_utils::create_test_fastpath;
    use tempfile::TempDir;

    #[test]
    fn test_pool_empty_on_creation() {
        let pool = SlidePool::new();
        assert_eq!(pool.len(), 0);
    }

    #[test]
    fn test_pool_load_returns_entry() {
        let temp = TempDir::new().unwrap();
        create_test_fastpath(temp.path());

        let pool = SlidePool::new();
        let entry = pool.load_or_get(1, temp.path()).unwrap();

        assert_eq!(entry.metadata.dimensions, (2048, 2048));
        assert_eq!(entry.metadata.tile_size, 512);
        assert_eq!(entry.metadata.num_levels(), 2);
        assert_eq!(pool.len(), 1);
    }

    #[test]
    fn test_pool_second_call_returns_cached() {
        let temp = TempDir::new().unwrap();
        create_test_fastpath(temp.path());

        let pool = SlidePool::new();
        let entry1 = pool.load_or_get(1, temp.path()).unwrap();
        let entry2 = pool.load_or_get(1, temp.path()).unwrap();

        assert!(Arc::ptr_eq(&entry1, &entry2));
        assert_eq!(pool.len(), 1);
    }

    #[test]
    fn test_pool_different_slides_independent() {
        let temp1 = TempDir::new().unwrap();
        let temp2 = TempDir::new().unwrap();
        create_test_fastpath(temp1.path());
        create_test_fastpath(temp2.path());

        let pool = SlidePool::new();
        let entry1 = pool.load_or_get(1, temp1.path()).unwrap();
        let entry2 = pool.load_or_get(2, temp2.path()).unwrap();

        assert!(!Arc::ptr_eq(&entry1, &entry2));
        assert_eq!(pool.len(), 2);
    }

    #[test]
    fn test_pool_invalid_path_returns_error() {
        let pool = SlidePool::new();
        let result = pool.load_or_get(1, Path::new("/nonexistent/path"));

        assert!(result.is_err());
        assert_eq!(pool.len(), 0);
    }
}
