//! Thread-safe LRU tile cache using DashMap.

use std::collections::VecDeque;
use std::sync::atomic::{AtomicU64, AtomicUsize, Ordering};

use dashmap::DashMap;
use parking_lot::Mutex;

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

/// Thread-safe LRU tile cache.
///
/// Uses DashMap for lock-free concurrent reads and a separate
/// LRU list (mutex-protected) for eviction ordering.
pub struct TileCache {
    /// Main data store - lock-free concurrent access.
    tiles: DashMap<TileCoord, TileData>,
    /// LRU order tracking - protected by mutex.
    lru_order: Mutex<VecDeque<TileCoord>>,
    /// Maximum cache size in bytes.
    max_size_bytes: usize,
    /// Current cache size in bytes.
    current_size: AtomicUsize,
    /// Cache hit count.
    hits: AtomicU64,
    /// Cache miss count.
    misses: AtomicU64,
}

impl TileCache {
    /// Create a new cache with the given size limit in megabytes.
    pub fn new(max_size_mb: usize) -> Self {
        Self {
            tiles: DashMap::new(),
            lru_order: Mutex::new(VecDeque::new()),
            max_size_bytes: max_size_mb * 1024 * 1024,
            current_size: AtomicUsize::new(0),
            hits: AtomicU64::new(0),
            misses: AtomicU64::new(0),
        }
    }

    /// Get a tile from the cache.
    ///
    /// Returns None if the tile is not cached.
    /// Updates LRU order on hit.
    pub fn get(&self, coord: &TileCoord) -> Option<TileData> {
        if let Some(entry) = self.tiles.get(coord) {
            self.hits.fetch_add(1, Ordering::Relaxed);

            // Update LRU order (move to back = most recently used)
            let mut lru = self.lru_order.lock();
            if let Some(pos) = lru.iter().position(|c| c == coord) {
                lru.remove(pos);
                lru.push_back(*coord);
            }

            Some(entry.value().clone())
        } else {
            self.misses.fetch_add(1, Ordering::Relaxed);
            None
        }
    }

    /// Insert a tile into the cache.
    ///
    /// Evicts least recently used tiles if necessary to stay within size limit.
    pub fn insert(&self, coord: TileCoord, data: TileData) {
        let tile_size = data.size_bytes();

        // Evict tiles if needed to make room
        self.evict_if_needed(tile_size);

        // Check if already exists (another thread might have inserted)
        if self.tiles.contains_key(&coord) {
            return;
        }

        // Insert into data store
        self.tiles.insert(coord, data);
        self.current_size.fetch_add(tile_size, Ordering::Relaxed);

        // Add to LRU order
        let mut lru = self.lru_order.lock();
        lru.push_back(coord);
    }

    /// Evict tiles until there's room for the new tile.
    fn evict_if_needed(&self, new_tile_size: usize) {
        let target_size = self.max_size_bytes.saturating_sub(new_tile_size);

        while self.current_size.load(Ordering::Relaxed) > target_size {
            let coord_to_evict = {
                let mut lru = self.lru_order.lock();
                lru.pop_front()
            };

            if let Some(coord) = coord_to_evict {
                if let Some((_, tile)) = self.tiles.remove(&coord) {
                    self.current_size
                        .fetch_sub(tile.size_bytes(), Ordering::Relaxed);
                }
            } else {
                // No more tiles to evict
                break;
            }
        }
    }

    /// Check if a tile is in the cache.
    pub fn contains(&self, coord: &TileCoord) -> bool {
        self.tiles.contains_key(coord)
    }

    /// Clear the cache.
    pub fn clear(&self) {
        self.tiles.clear();
        self.lru_order.lock().clear();
        self.current_size.store(0, Ordering::Relaxed);
        // Don't reset stats - keep for debugging
    }

    /// Get cache statistics.
    pub fn stats(&self) -> CacheStats {
        CacheStats {
            hits: self.hits.load(Ordering::Relaxed),
            misses: self.misses.load(Ordering::Relaxed),
            size_bytes: self.current_size.load(Ordering::Relaxed),
            num_tiles: self.tiles.len(),
        }
    }

    /// Get the number of cached tiles.
    pub fn len(&self) -> usize {
        self.tiles.len()
    }

    /// Check if cache is empty.
    pub fn is_empty(&self) -> bool {
        self.tiles.is_empty()
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
    fn test_cache_eviction() {
        // Create a small cache (1KB)
        let cache = TileCache::new(0); // 0MB = effectively ~0 bytes
        cache.current_size.store(0, Ordering::Relaxed);

        // Manually set a tiny max size for testing
        let small_cache = TileCache {
            tiles: DashMap::new(),
            lru_order: Mutex::new(VecDeque::new()),
            max_size_bytes: 500, // 500 bytes
            current_size: AtomicUsize::new(0),
            hits: AtomicU64::new(0),
            misses: AtomicU64::new(0),
        };

        // Insert tiles that will exceed the limit
        small_cache.insert(TileCoord::new(0, 0, 0), make_tile(200));
        small_cache.insert(TileCoord::new(0, 0, 1), make_tile(200));

        // This should trigger eviction
        small_cache.insert(TileCoord::new(0, 0, 2), make_tile(200));

        // First tile should have been evicted
        assert!(small_cache.get(&TileCoord::new(0, 0, 0)).is_none());
        // Later tiles should still be there
        assert!(small_cache.get(&TileCoord::new(0, 0, 2)).is_some());
    }

    #[test]
    fn test_cache_clear() {
        let cache = TileCache::new(10);
        cache.insert(TileCoord::new(0, 1, 2), make_tile(100));
        cache.insert(TileCoord::new(0, 3, 4), make_tile(100));

        cache.clear();

        assert!(cache.is_empty());
        assert_eq!(cache.stats().size_bytes, 0);
    }

    #[test]
    fn test_lru_order() {
        // Max 350 bytes, each tile is 150 bytes
        // So only 2 tiles can fit (300 bytes)
        let cache = TileCache {
            tiles: DashMap::new(),
            lru_order: Mutex::new(VecDeque::new()),
            max_size_bytes: 350,
            current_size: AtomicUsize::new(0),
            hits: AtomicU64::new(0),
            misses: AtomicU64::new(0),
        };

        let coord1 = TileCoord::new(0, 0, 0);
        let coord2 = TileCoord::new(0, 0, 1);
        let coord3 = TileCoord::new(0, 0, 2);

        cache.insert(coord1, make_tile(150));
        cache.insert(coord2, make_tile(150));

        // Access coord1 to make it recently used
        cache.get(&coord1);

        // Insert coord3, which should evict coord2 (least recently used)
        cache.insert(coord3, make_tile(150));

        assert!(cache.get(&coord1).is_some()); // Should still exist
        assert!(cache.get(&coord2).is_none()); // Should be evicted
        assert!(cache.get(&coord3).is_some()); // Should exist
    }
}
