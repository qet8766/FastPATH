# Multi-Slide Compressed Cache — Incremental Implementation Plan

The original plan failed because too many things changed at once and panning lag
couldn't be traced. This plan decomposes the work into 8 parts, each independently
shippable, testable, and revertable. Each part has a **verification gate** — a
concrete check that must pass before moving on.

---

## Part 1: Decoder Split

**Goal:** Split `decode_tile()` into `read_jpeg_bytes()` + `decode_jpeg_bytes()`.
Pure internal refactor — no behavioral change, no new types.

**File:** `src/fastpath_core/src/decoder.rs`

**Changes:**
- Add `CompressedTileData { jpeg_bytes: Bytes, width: u32, height: u32 }` struct
  with `size_bytes()` returning `jpeg_bytes.len()`
- Add `read_jpeg_bytes(path: &Path) -> TileResult<CompressedTileData>` — reads
  file, parses JPEG header for dimensions via `zune_jpeg` `decode_headers()`,
  returns raw bytes + w/h
- Add `decode_jpeg_bytes(compressed: &CompressedTileData) -> TileResult<TileData>`
  — SIMD decodes JPEG bytes to RGB (handles grayscale→RGB conversion)
- Keep existing `decode_tile()` unchanged — it calls `read_jpeg_bytes()` then
  `decode_jpeg_bytes()` internally
- Add unit tests for both new functions

**Risk:** Zero. Existing `decode_tile()` is unchanged. New functions are additive.

**Verification gate:**
```
cargo test          # All existing + new tests pass
cargo clippy -- -D warnings  # Clean
```

---

## Part 2: Compressed Cache Types

**Goal:** Add L2 cache types to `cache.rs`. Pure addition — nothing uses them yet.

**File:** `src/fastpath_core/src/cache.rs`

**Changes:**
- Add `SlideTileCoord { slide_id: u64, level: u32, col: u32, row: u32 }` with
  `Hash`, `Eq`, `Clone`, `Copy`
- Add `compute_slide_id(path: &str) -> u64` using `std::hash::DefaultHasher`
- Add `CompressedTileCache` — new moka `Cache<SlideTileCoord, CompressedTileData>`
  with `new(max_size_mb)`, `get()`, `insert()`, `contains()`, `stats()`. Same
  pattern as `TileCache` but weighted by JPEG size. **No `clear()` method** — this
  cache survives slide switches.
- Re-export `CompressedTileData` from `decoder.rs` (or move the struct to
  `cache.rs` and import from decoder — design decision at implementation time)
- Add unit tests for all new types and methods

**Risk:** Zero. New types are additive and not referenced by scheduler.

**Verification gate:**
```
cargo test
cargo clippy -- -D warnings
```

---

## Part 3: L2 Write-Through (Populate L2, Don't Read It)

**Goal:** Add L2 cache field to `TileScheduler`. On every disk read, write the
compressed JPEG bytes into L2 as a side effect. **`get_tile()` still only reads
L1 → disk.** L2 is populated but never consulted for reads.

This lets us measure whether the L2 write overhead causes panning lag *before*
we change the read path.

**Files:** `scheduler.rs`, `lib.rs`

**Changes to `scheduler.rs`:**
- Add fields: `l2_cache: Arc<CompressedTileCache>`, `active_slide_id: RwLock<Option<u64>>`
- Update `new()` → `new(cache_size_mb, l2_cache_size_mb, prefetch_distance)`
- In `load()`: compute slide_id, store in `active_slide_id`. Clear L1 as before.
  Do NOT clear L2.
- In `load_tile_into_cache()` and `load_tile_for_prefetch()`: after reading from
  disk, also insert compressed bytes into L2 (using `read_jpeg_bytes()` then
  `decode_jpeg_bytes()` instead of `decode_tile()`). L1 insert unchanged.
- `get_tile()`: **unchanged read path** — still L1 → disk. But disk reads now
  use the split decoder and write to L2.
- In `close()`: clear L1 only. Set `active_slide_id` to None.
- Update `cache_stats()` to also return L2 stats.

**Changes to `lib.rs`:**
- Update constructor: `#[pyo3(signature = (cache_size_mb=4096, l2_cache_size_mb=32768, prefetch_distance=3))]`
- Update `cache_stats()` to include L2 keys (l2_hits, l2_misses, l2_size_bytes, l2_num_tiles)
- Keep all other methods identical

**Risk:** Low. The read path is unchanged. The only new work is an L2 insert
(moka insert is ~200ns) on each disk read, which is already 5-10ms. Negligible
overhead.

**Verification gate:**
```
cargo test
cargo clippy -- -D warnings
uv run python -m pytest tests/
# Manual: open a slide, pan around, check panning feels identical to before
# Manual: check cache_stats() shows L2 being populated
```

---

## Part 4: L2 Read Path (Two-Tier Lookup)

**Goal:** Enable L2 reads in `get_tile()`. This is the performance-critical change.

**File:** `scheduler.rs`

**Changes:**
- `get_tile()` now: L1 → L2 → disk
  - L1 hit → return (same as before)
  - L2 hit → `decode_jpeg_bytes()` → insert L1 → return (~2-3ms)
  - Disk → `read_jpeg_bytes()` → insert L2 → `decode_jpeg_bytes()` → insert L1 → return
- `load_tile_for_prefetch()` — same two-tier flow with generation guards
- `prefetch_low_res_levels()` — check L2 before disk (fast when L2 is warm)
- `filter_cached_tiles()` — check both L1 and L2

**Risk:** Medium. This changes the hot path. The L2 lookup (moka get, ~100ns)
adds negligible latency on L1 hit. On L2 hit, JPEG decode (~2ms) replaces disk
read (~5-10ms), which is faster. The risk is lock contention if moka's internal
sharding doesn't handle the concurrent access pattern well.

**Verification gate:**
```
cargo test
cargo clippy -- -D warnings
uv run python -m pytest tests/
# CRITICAL: Manual panning test
#   1. Open a slide, pan around at various zoom levels
#   2. Compare perceived smoothness to Part 3 (before L2 reads)
#   3. If panning feels laggier, STOP and investigate before proceeding
# Manual: open same slide twice — second open should be faster (L2 warm)
```

---

## Part 5: Python Config + Constructor Update

**Goal:** Wire the new L2 parameters through Python config and app startup.

**Files:** `config.py`, `app.py`

**Changes to `config.py`:**
- Replace `TILE_CACHE_SIZE_MB` with `L1_CACHE_SIZE_MB = _get_env_int("FASTPATH_L1_CACHE_MB", 512)`
- Add `L2_CACHE_SIZE_MB = _get_env_int("FASTPATH_L2_CACHE_MB", 32768)`
- Keep `PYTHON_TILE_CACHE_SIZE` for now (remove later in Part 8)
- Update `_validate_config()` for new params

**Changes to `app.py`:**
- Update `RustTileScheduler` construction to use new config constants
- Update `CacheStatsProvider` (if it exists) to show L2 stats

**Risk:** Low. Config changes, no behavioral change.

**Verification gate:**
```
uv run python -m pytest tests/
# Manual: verify app starts, verify cache_stats() shows L1 + L2 separately
```

---

## Part 6: SlidePool + Metadata Persistence

**Goal:** Avoid re-parsing `metadata.json` on slide revisit. Metadata for all
visited slides stays in memory.

**Files:** New `slide_pool.rs`, modify `scheduler.rs`, `lib.rs`

**Changes:**
- Create `slide_pool.rs`:
  - `SlideEntry { metadata: SlideMetadata, resolver: TilePathResolver, path: PathBuf }`
  - `SlidePool { slides: RwLock<HashMap<u64, SlideEntry>> }`
  - Methods: `load_or_get(path) -> TileResult<u64>` (idempotent), `with_slide(id, closure)`,
    `contains(id)`, `remove(id)`
- In `scheduler.rs`: replace `slide: RwLock<Option<SlideState>>` with
  `slide_pool: Arc<SlidePool>`. The `active_slide_id` field (added in Part 3)
  already tracks which slide is current.
- `load()`: calls `slide_pool.load_or_get(path)` — if slide was loaded before,
  reuses metadata + resolver without re-parsing JSON.
- Metadata accessors (`tile_size()`, `num_levels()`, etc.) read from slide_pool
  via `active_slide_id`.
- In `lib.rs`: no API changes (slide_pool is internal).

**Risk:** Medium. Replaces the `slide` field — the most-accessed field in
`TileScheduler`. The `with_slide()` closure pattern adds an RwLock read on every
`get_tile()`. Profile to ensure this doesn't cause contention.

**Alternative if RwLock is too slow:** Store a clone of active `SlideEntry` fields
(metadata + resolver) directly on the scheduler, bypassing the pool for hot-path
access. Pool only used for load/switch.

**Verification gate:**
```
cargo test
cargo clippy -- -D warnings
uv run python -m pytest tests/
# Manual: open slide A, switch to B, switch back to A — second load of A should
#   be noticeably faster (no metadata parse)
# Manual: panning test — verify no regression from Part 4
```

---

## Part 7: Bulk Preloader

**Goal:** Background preload all slides in a directory into L2.

**Files:** New `bulk_preload.rs`, modify `scheduler.rs`, `lib.rs`, `app.py`,
`navigator.py`

**Rust changes:**
- Create `bulk_preload.rs`:
  - `BulkPreloadStatus { slides_total, slides_done, tiles_loaded, tiles_failed, tiles_skipped, is_running }`
  - `BulkPreloader { pool: rayon::ThreadPool, l2_cache, slide_pool, cancelled, counters }`
  - `start_preload(paths, target_level_from_top)` — dedicated 3-thread rayon pool,
    reads JPEG tiles from disk into L2. Priority: starts from current index,
    expands outward (±1, ±2, ...).
  - `cancel()`, `status()`
- In `scheduler.rs`: add `bulk_preloader` field, delegation methods
- In `lib.rs`: expose `start_bulk_preload()`, `cancel_bulk_preload()`, `bulk_preload_status()`

**Python changes:**
- In `navigator.py`: add `slidePaths` property returning list of paths
- In `app.py`: after `openSlide()` + navigator scan, call `_maybe_start_bulk_preload()`
  which collects paths from navigator and starts preload

**Risk:** Low for correctness (preloader is fire-and-forget background work).
Medium for resource contention — 3 extra threads doing disk I/O could compete
with foreground tile loading. Mitigate by using a separate rayon pool (not the
global one) with lower priority.

**Verification gate:**
```
cargo test
cargo clippy -- -D warnings
uv run python -m pytest tests/
# Manual: open a directory with 10+ slides
#   1. Check stderr for [BULK PRELOAD] progress logs
#   2. Wait for completion
#   3. Navigate with arrow keys — slides should load with no gray tiles
#   4. Verify panning is NOT affected during preload
```

---

## Part 8: Cleanup

**Goal:** Remove dead code, optimize FFI.

**Files:** `slide.py`, `config.py`, `lib.rs`, `providers.py`

**Changes:**
- `slide.py`: remove `_tile_cache`, `_cache_size`, `_cache_lock`, `_cache_hits`,
  `_cache_misses`, `_cache_get()`, `_cache_put()`, `get_cache_stats()`. Simplify
  `getTile()` to direct disk load (only used by tests).
- `config.py`: remove `PYTHON_TILE_CACHE_SIZE`
- `lib.rs` (optional): `get_tile()` returns `Py<PyBytes>` instead of `Vec<u8>`
  to eliminate one 768KB copy per tile. **Test this separately** — PyBytes
  lifetime semantics differ from Vec.
- `providers.py`: no changes needed (PyBytes is bytes in Python)

**Risk:** Low. Removing dead code. The PyBytes optimization is the only risky
part and is optional.

**Verification gate:**
```
cargo test (if lib.rs changed)
cargo clippy -- -D warnings
uv run python -m pytest tests/
# Manual: full functional test
```

---

## Summary: Risk Map

| Part | Description                  | Risk   | Revertable | Files Changed     |
|------|------------------------------|--------|------------|-------------------|
| 1    | Decoder split                | Zero   | Trivially  | decoder.rs        |
| 2    | Compressed cache types       | Zero   | Trivially  | cache.rs          |
| 3    | L2 write-through             | Low    | Yes        | scheduler.rs, lib.rs |
| 4    | L2 read path                 | Medium | Yes        | scheduler.rs      |
| 5    | Python config                | Low    | Yes        | config.py, app.py |
| 6    | SlidePool + metadata persist | Medium | Yes        | slide_pool.rs, scheduler.rs |
| 7    | Bulk preloader               | Medium | Yes        | bulk_preload.rs, app.py, navigator.py |
| 8    | Cleanup + FFI opt            | Low    | Yes        | slide.py, config.py, lib.rs |

**Key principle:** After each part, run the full verification gate. If panning
feels laggier than the previous part, stop and bisect before proceeding. The
most likely culprits for the original lag are Parts 4 and 6.
