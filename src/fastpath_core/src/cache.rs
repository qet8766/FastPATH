//! Thread-safe tile cache using moka (TinyLFU eviction).

use std::sync::atomic::{AtomicU64, Ordering};

use moka::sync::Cache;

use crate::decoder::TileData;

/// Tile coordinate key.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct TileCoord {
    pub level: u32,
    pub col: u32,
    pub row: u32,
}

impl TileCoord {
    pub fn new(level: u32, col: u32, row: u32) -> Self {
        Self { level, col, row }
    }
}

/// Cache statistics.
#[derive(Debug, Clone, Default)]
pub struct CacheStats {
    pub hits: u64,
    pub misses: u64,
    pub size_bytes: usize,
    pub num_tiles: usize,
}

/// Thread-safe tile cache with TinyLFU eviction.
///
/// Uses moka::sync::Cache for O(1) lock-free concurrent reads,
/// size-aware eviction via a weigher, and internal sharding.
pub struct TileCache {
    inner: Cache<TileCoord, TileData>,
    /// Cache hit count.
    hits: AtomicU64,
    /// Cache miss count.
    misses: AtomicU64,
}

impl TileCache {
    /// Create a new cache with the given size limit in megabytes.
    pub fn new(max_size_mb: usize) -> Self {
        let max_bytes = (max_size_mb as u64) * 1024 * 1024;
        let inner = Cache::builder()
            .max_capacity(max_bytes)
            .weigher(|_key: &TileCoord, value: &TileData| -> u32 {
                value.size_bytes().try_into().unwrap_or(u32::MAX)
            })
            .build();
        Self {
            inner,
            hits: AtomicU64::new(0),
            misses: AtomicU64::new(0),
        }
    }

    /// Get a tile from the cache.
    ///
    /// Returns None if the tile is not cached.
    pub fn get(&self, coord: &TileCoord) -> Option<TileData> {
        if let Some(tile) = self.inner.get(coord) {
            self.hits.fetch_add(1, Ordering::Relaxed);
            Some(tile)
        } else {
            self.misses.fetch_add(1, Ordering::Relaxed);
            None
        }
    }

    /// Insert a tile into the cache.
    ///
    /// Eviction is handled internally by moka when capacity is exceeded.
    pub fn insert(&self, coord: TileCoord, data: TileData) {
        self.inner.insert(coord, data);
    }

    /// Check if a tile is in the cache.
    pub fn contains(&self, coord: &TileCoord) -> bool {
        self.inner.contains_key(coord)
    }

    /// Clear the cache.
    pub fn clear(&self) {
        self.inner.invalidate_all();
        // Don't reset stats - keep for debugging
    }

    /// Get cache statistics.
    pub fn stats(&self) -> CacheStats {
        CacheStats {
            hits: self.hits.load(Ordering::Relaxed),
            misses: self.misses.load(Ordering::Relaxed),
            size_bytes: self.inner.weighted_size() as usize,
            num_tiles: self.inner.entry_count() as usize,
        }
    }

    /// Check if cache is empty.
    pub fn is_empty(&self) -> bool {
        self.inner.entry_count() == 0
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn make_tile(size: usize) -> TileData {
        TileData::new(vec![0u8; size], 1, 1)
    }

    #[test]
    fn test_cache_insert_and_get() {
        let cache = TileCache::new(10); // 10MB
        let coord = TileCoord::new(0, 1, 2);
        let tile = make_tile(1000);

        cache.insert(coord, tile.clone());

        let retrieved = cache.get(&coord);
        assert!(retrieved.is_some());
        assert_eq!(retrieved.unwrap().data.len(), 1000);
    }

    #[test]
    fn test_cache_miss() {
        let cache = TileCache::new(10);
        let coord = TileCoord::new(0, 99, 99);

        let result = cache.get(&coord);
        assert!(result.is_none());

        let stats = cache.stats();
        assert_eq!(stats.misses, 1);
    }

    #[test]
    fn test_cache_hit_stats() {
        let cache = TileCache::new(10);
        let coord = TileCoord::new(0, 1, 2);
        cache.insert(coord, make_tile(100));

        cache.get(&coord);
        cache.get(&coord);

        let stats = cache.stats();
        assert_eq!(stats.hits, 2);
    }

    #[test]
    fn test_cache_clear() {
        let cache = TileCache::new(10);
        cache.insert(TileCoord::new(0, 1, 2), make_tile(100));
        cache.insert(TileCoord::new(0, 3, 4), make_tile(100));

        cache.clear();
        // moka clears asynchronously; run_pending forces completion
        cache.inner.run_pending_tasks();

        assert!(cache.is_empty());
        assert_eq!(cache.stats().size_bytes, 0);
    }
}
