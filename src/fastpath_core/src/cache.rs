//! Thread-safe tile cache using moka (TinyLFU eviction).

use std::fmt;
use std::hash::{Hash, Hasher};
use std::sync::atomic::{AtomicU64, Ordering};

use moka::sync::Cache;

use crate::decoder::{CompressedTileData, TileData};

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

impl fmt::Display for TileCoord {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}/{}_{}", self.level, self.col, self.row)
    }
}

/// Tile coordinate key that includes a slide identifier.
///
/// Used by `CompressedTileCache` (L2) so tiles from multiple slides
/// can coexist in the same cache without collisions.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct SlideTileCoord {
    pub slide_id: u64,
    pub level: u32,
    pub col: u32,
    pub row: u32,
}

impl SlideTileCoord {
    pub fn new(slide_id: u64, level: u32, col: u32, row: u32) -> Self {
        Self {
            slide_id,
            level,
            col,
            row,
        }
    }
}

/// Cache statistics.
#[derive(Debug, Clone, Default)]
pub struct CacheStats {
    pub hits: u64,
    pub misses: u64,
    pub hit_ratio: f64,
    pub size_bytes: usize,
    pub num_tiles: usize,
}

/// Trait for cache values that report their size in bytes.
pub trait Weighted: Clone + Send + Sync + 'static {
    fn size_bytes(&self) -> usize;
}

impl Weighted for TileData {
    fn size_bytes(&self) -> usize {
        self.data.len()
    }
}

impl Weighted for CompressedTileData {
    fn size_bytes(&self) -> usize {
        self.jpeg_bytes.len()
    }
}

/// Thread-safe cache with TinyLFU eviction and hit/miss tracking.
///
/// Generic over key and value types. Uses moka::sync::Cache for O(1)
/// lock-free concurrent reads, size-aware eviction via a weigher,
/// and internal sharding.
pub struct TrackedCache<K, V>
where
    K: Hash + Eq + Send + Sync + Clone + 'static,
    V: Weighted,
{
    inner: Cache<K, V>,
    /// Cache hit count.
    hits: AtomicU64,
    /// Cache miss count.
    misses: AtomicU64,
}

impl<K, V> TrackedCache<K, V>
where
    K: Hash + Eq + Send + Sync + Clone + 'static,
    V: Weighted,
{
    /// Create a new cache with the given size limit in megabytes.
    pub fn new(max_size_mb: usize) -> Self {
        let max_bytes = (max_size_mb as u64) * 1024 * 1024;
        let inner = Cache::builder()
            .max_capacity(max_bytes)
            .weigher(|_key: &K, value: &V| -> u32 {
                Weighted::size_bytes(value).try_into().unwrap_or(u32::MAX)
            })
            .build();
        Self {
            inner,
            hits: AtomicU64::new(0),
            misses: AtomicU64::new(0),
        }
    }

    /// Get a value from the cache.
    ///
    /// Returns None if the key is not cached.
    pub fn get(&self, key: &K) -> Option<V> {
        if let Some(value) = self.inner.get(key) {
            self.hits.fetch_add(1, Ordering::Relaxed);
            Some(value)
        } else {
            self.misses.fetch_add(1, Ordering::Relaxed);
            None
        }
    }

    /// Insert a value into the cache.
    ///
    /// Eviction is handled internally by moka when capacity is exceeded.
    pub fn insert(&self, key: K, value: V) {
        self.inner.insert(key, value);
    }

    /// Check if a key is in the cache.
    pub fn contains(&self, key: &K) -> bool {
        self.inner.contains_key(key)
    }

    /// Clear the cache.
    ///
    /// Runs pending eviction tasks synchronously so entries are gone before
    /// return, and resets hit/miss counters so each slide starts fresh.
    pub fn clear(&self) {
        self.inner.invalidate_all();
        self.inner.run_pending_tasks();
        self.reset_stats();
    }

    /// Reset hit/miss counters to zero.
    pub fn reset_stats(&self) {
        self.hits.store(0, Ordering::Relaxed);
        self.misses.store(0, Ordering::Relaxed);
    }

    /// Get cache statistics.
    ///
    /// Runs pending moka maintenance first so `entry_count()` and
    /// `weighted_size()` reflect the latest inserts/evictions.
    pub fn stats(&self) -> CacheStats {
        self.inner.run_pending_tasks();
        let hits = self.hits.load(Ordering::Relaxed);
        let misses = self.misses.load(Ordering::Relaxed);
        let total = hits + misses;
        let hit_ratio = if total > 0 { hits as f64 / total as f64 } else { 0.0 };
        CacheStats {
            hits,
            misses,
            hit_ratio,
            size_bytes: self.inner.weighted_size() as usize,
            num_tiles: self.inner.entry_count() as usize,
        }
    }

    /// Check if cache is empty (used in tests).
    #[allow(dead_code)]
    pub fn is_empty(&self) -> bool {
        self.inner.entry_count() == 0
    }
}

/// L1 decoded RGB tile cache — cleared on slide switch.
pub type TileCache = TrackedCache<TileCoord, TileData>;

/// L2 compressed JPEG cache — persists across slide switches.
///
/// Unlike `TileCache` (L1), this cache is **not** cleared on slide switch.
/// Tiles from different slides are disambiguated by `SlideTileCoord.slide_id`.
pub type CompressedTileCache = TrackedCache<SlideTileCoord, CompressedTileData>;

/// Compute a slide identifier by hashing its path string.
///
/// Uses `DefaultHasher` (SipHash-2-4). Not stable across Rust versions,
/// but that's fine — the L2 cache is in-memory only, no persistence.
pub fn compute_slide_id(path: &str) -> u64 {
    let mut hasher = std::collections::hash_map::DefaultHasher::new();
    path.hash(&mut hasher);
    hasher.finish()
}

#[cfg(test)]
mod tests {
    use bytes::Bytes;

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
        assert_eq!(stats.hit_ratio, 0.0);
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
        assert_eq!(stats.hit_ratio, 1.0);
    }

    #[test]
    fn test_cache_clear() {
        let cache = TileCache::new(10);
        cache.insert(TileCoord::new(0, 1, 2), make_tile(100));
        cache.insert(TileCoord::new(0, 3, 4), make_tile(100));

        // Generate some hits/misses before clearing
        cache.get(&TileCoord::new(0, 1, 2));
        cache.get(&TileCoord::new(0, 99, 99));

        cache.clear();

        assert!(cache.is_empty());
        let stats = cache.stats();
        assert_eq!(stats.size_bytes, 0);
        assert_eq!(stats.hits, 0);
        assert_eq!(stats.misses, 0);
        assert_eq!(stats.hit_ratio, 0.0);
    }

    #[test]
    fn test_hit_ratio_mixed() {
        let cache = TileCache::new(10);
        let coord = TileCoord::new(0, 1, 2);
        cache.insert(coord, make_tile(100));

        // 3 hits
        cache.get(&coord);
        cache.get(&coord);
        cache.get(&coord);
        // 1 miss
        cache.get(&TileCoord::new(0, 99, 99));

        let stats = cache.stats();
        assert_eq!(stats.hits, 3);
        assert_eq!(stats.misses, 1);
        assert!((stats.hit_ratio - 0.75).abs() < f64::EPSILON);
    }

    #[test]
    fn test_stats_after_clear() {
        let cache = TileCache::new(10);
        let coord = TileCoord::new(0, 1, 2);
        cache.insert(coord, make_tile(100));
        // Force moka to process the insert
        cache.inner.run_pending_tasks();

        // Generate hits and misses
        cache.get(&coord);
        cache.get(&coord);
        cache.get(&TileCoord::new(0, 99, 99));

        // Verify non-zero before clear
        let stats = cache.stats();
        assert!(stats.hits > 0);
        assert!(stats.misses > 0);
        assert!(stats.num_tiles > 0);

        cache.clear();

        let stats = cache.stats();
        assert_eq!(stats.hits, 0);
        assert_eq!(stats.misses, 0);
        assert_eq!(stats.hit_ratio, 0.0);
        assert_eq!(stats.size_bytes, 0);
        assert_eq!(stats.num_tiles, 0);
    }

    // --- TileCoord Display ---

    #[test]
    fn test_tile_coord_display() {
        let coord = TileCoord::new(2, 5, 3);
        assert_eq!(format!("{}", coord), "2/5_3");
    }

    // --- SlideTileCoord tests ---

    #[test]
    fn test_slide_tile_coord_new() {
        let c = SlideTileCoord::new(42, 3, 10, 20);
        assert_eq!(c.slide_id, 42);
        assert_eq!(c.level, 3);
        assert_eq!(c.col, 10);
        assert_eq!(c.row, 20);
    }

    #[test]
    fn test_slide_tile_coord_equality() {
        let a = SlideTileCoord::new(1, 2, 3, 4);
        let b = SlideTileCoord::new(1, 2, 3, 4);
        let c = SlideTileCoord::new(99, 2, 3, 4);
        assert_eq!(a, b);
        assert_ne!(a, c);
    }

    #[test]
    fn test_slide_tile_coord_hash_differs_by_slide_id() {
        use std::collections::hash_map::DefaultHasher;

        let hash_of = |c: &SlideTileCoord| -> u64 {
            let mut h = DefaultHasher::new();
            c.hash(&mut h);
            h.finish()
        };

        let a = SlideTileCoord::new(1, 0, 5, 5);
        let b = SlideTileCoord::new(2, 0, 5, 5);
        assert_ne!(hash_of(&a), hash_of(&b));
    }

    #[test]
    fn test_slide_tile_coord_copy() {
        let a = SlideTileCoord::new(1, 2, 3, 4);
        let b = a; // Copy
        assert_eq!(a, b); // `a` still usable after copy
    }

    // --- compute_slide_id tests ---

    #[test]
    fn test_compute_slide_id_deterministic() {
        let id1 = compute_slide_id("/slides/test.fastpath");
        let id2 = compute_slide_id("/slides/test.fastpath");
        assert_eq!(id1, id2);
    }

    #[test]
    fn test_compute_slide_id_different_paths_differ() {
        let id1 = compute_slide_id("/slides/a.fastpath");
        let id2 = compute_slide_id("/slides/b.fastpath");
        assert_ne!(id1, id2);
    }

    #[test]
    fn test_compute_slide_id_empty_string() {
        // Should not panic
        let _id = compute_slide_id("");
    }

    // --- CompressedTileCache tests ---

    fn make_compressed_tile(size: usize) -> CompressedTileData {
        CompressedTileData {
            jpeg_bytes: Bytes::from(vec![0u8; size]),
            width: 512,
            height: 512,
        }
    }

    #[test]
    fn test_compressed_cache_insert_and_get() {
        let cache = CompressedTileCache::new(10);
        let coord = SlideTileCoord::new(1, 0, 1, 2);
        let tile = make_compressed_tile(500);

        cache.insert(coord, tile);

        let retrieved = cache.get(&coord);
        assert!(retrieved.is_some());
        assert_eq!(retrieved.unwrap().jpeg_bytes.len(), 500);
    }

    #[test]
    fn test_compressed_cache_miss() {
        let cache = CompressedTileCache::new(10);
        let coord = SlideTileCoord::new(1, 0, 99, 99);

        let result = cache.get(&coord);
        assert!(result.is_none());

        let stats = cache.stats();
        assert_eq!(stats.misses, 1);
        assert_eq!(stats.hit_ratio, 0.0);
    }

    #[test]
    fn test_compressed_cache_hit_stats() {
        let cache = CompressedTileCache::new(10);
        let coord = SlideTileCoord::new(1, 0, 1, 2);
        cache.insert(coord, make_compressed_tile(100));

        cache.get(&coord);
        cache.get(&coord);

        let stats = cache.stats();
        assert_eq!(stats.hits, 2);
        assert_eq!(stats.hit_ratio, 1.0);
    }

    #[test]
    fn test_compressed_cache_mixed_hit_ratio() {
        let cache = CompressedTileCache::new(10);
        let coord = SlideTileCoord::new(1, 0, 1, 2);
        cache.insert(coord, make_compressed_tile(100));

        // 3 hits
        cache.get(&coord);
        cache.get(&coord);
        cache.get(&coord);
        // 1 miss
        cache.get(&SlideTileCoord::new(1, 0, 99, 99));

        let stats = cache.stats();
        assert_eq!(stats.hits, 3);
        assert_eq!(stats.misses, 1);
        assert!((stats.hit_ratio - 0.75).abs() < f64::EPSILON);
    }

    #[test]
    fn test_compressed_cache_contains() {
        let cache = CompressedTileCache::new(10);
        let coord = SlideTileCoord::new(1, 0, 1, 2);

        assert!(!cache.contains(&coord));
        cache.insert(coord, make_compressed_tile(100));
        assert!(cache.contains(&coord));
    }

    #[test]
    fn test_compressed_cache_multi_slide_isolation() {
        let cache = CompressedTileCache::new(10);
        let coord_a = SlideTileCoord::new(1, 0, 5, 5);
        let coord_b = SlideTileCoord::new(2, 0, 5, 5);

        cache.insert(coord_a, make_compressed_tile(100));

        assert!(cache.get(&coord_a).is_some());
        assert!(cache.get(&coord_b).is_none());
    }

    #[test]
    fn test_compressed_cache_is_empty() {
        let cache = CompressedTileCache::new(10);
        assert!(cache.is_empty());

        cache.insert(SlideTileCoord::new(1, 0, 0, 0), make_compressed_tile(100));
        cache.inner.run_pending_tasks();
        assert!(!cache.is_empty());
    }

    #[test]
    fn test_compressed_cache_reset_stats_preserves_tiles() {
        let cache = CompressedTileCache::new(10);
        let coord = SlideTileCoord::new(1, 0, 1, 2);
        cache.insert(coord, make_compressed_tile(100));
        cache.inner.run_pending_tasks();

        // Generate some stats
        cache.get(&coord);
        cache.get(&SlideTileCoord::new(1, 0, 99, 99));

        let stats_before = cache.stats();
        assert!(stats_before.hits > 0);
        assert!(stats_before.misses > 0);
        assert!(stats_before.num_tiles > 0);

        cache.reset_stats();

        let stats_after = cache.stats();
        assert_eq!(stats_after.hits, 0);
        assert_eq!(stats_after.misses, 0);
        assert_eq!(stats_after.hit_ratio, 0.0);
        // Tiles are still there
        assert!(stats_after.num_tiles > 0);
        assert!(cache.get(&coord).is_some());
    }

    #[test]
    fn test_compressed_cache_weighted_size() {
        let cache = CompressedTileCache::new(10);
        let coord = SlideTileCoord::new(1, 0, 0, 0);
        cache.insert(coord, make_compressed_tile(2048));
        cache.inner.run_pending_tasks();

        let stats = cache.stats();
        assert_eq!(stats.size_bytes, 2048);
    }

    #[test]
    fn test_compressed_cache_no_clear_method() {
        // CompressedTileCache (L2) should not be cleared on slide switch.
        // Verify tiles survive by inserting, then checking they persist
        // after operations that would clear an L1 cache.
        let cache = CompressedTileCache::new(10);
        let coord = SlideTileCoord::new(1, 0, 1, 2);
        cache.insert(coord, make_compressed_tile(100));

        // reset_stats does NOT remove tiles
        cache.reset_stats();

        assert!(cache.contains(&coord));
        assert!(cache.get(&coord).is_some());
    }
}
