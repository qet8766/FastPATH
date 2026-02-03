# Multi-Slide Compressed Cache — Incremental Implementation Plan

The original plan failed because too many things changed at once and panning lag
couldn't be traced. This plan decomposes the work into 8 parts, each independently
shippable, testable, and revertable. Each part has a **verification gate** — a
concrete check that must pass before moving on.

---

## ~~Part 1: Decoder Split~~ DONE

Split `decode_tile()` into `read_jpeg_bytes()` + `decode_jpeg_bytes()` in
`decoder.rs`. Added `CompressedTileData` struct. Pure additive refactor.

## ~~Part 2: Compressed Cache Types~~ DONE

Added `SlideTileCoord`, `compute_slide_id()`, `CompressedTileCache` to
`cache.rs`. No `clear()` method — L2 survives slide switches.

## ~~Part 3: L2 Write-Through~~ DONE

Added `l2_cache` and `active_slide_id` to `TileScheduler`. Every disk read
writes compressed JPEG bytes into L2 as a side effect. `get_tile()` still
reads L1 → disk only. L2 is populated but never read. Updated `lib.rs`
constructor and `cache_stats()`.

---

## Part 4: L2 Read Path (Two-Tier Lookup) ← CURRENT

**Goal:** Enable L2 reads. Change tile lookup from L1→disk to L1→L2→disk.

**Files:** `scheduler.rs`, `cache.rs` (dead_code cleanup only)

### Changes

**1. `get_tile()` — add L2 between L1 and disk (scheduler.rs:349)**

```
L1 hit → return (unchanged)
L2 hit → decode_jpeg_bytes() → insert L1 → return (~2ms)
Miss   → resolve path → load_tile_into_cache() (disk, unchanged)
```

L2 check goes BEFORE path resolution to avoid the `slide.read()` lock on hit.
Guard with `slide_id != 0`. On decode failure, fall through to disk.

**2. `load_tile_for_prefetch()` — add L2 before in-flight claim (scheduler.rs:244)**

Insert between existing L1 check (line 259) and in-flight claim (line 264):

```
Generation check 1 (existing)
L1 hit (existing)
L2 hit → generation check → decode → generation check → insert L1 → return
In-flight claim → disk read → L2 write → decode → L1 insert (existing)
```

L2 check is before in-flight because L2 decode (~2ms) doesn't need dedup
like disk I/O (~5-10ms). Minor duplicate work if two threads hit same L2
entry simultaneously — acceptable.

**3. `filter_cached_tiles()` — check both L1 and L2 (scheduler.rs:519)**

Load `slide_id` once, check L1 first, then L2 if L1 misses. L2 tiles can be
decoded in ~2ms, fast enough to count as "available" for the cache miss
threshold.

**4. `cache.rs` — remove `#[allow(dead_code)]` (lines 192, 210)**

Remove from `CompressedTileCache::get()` and `::contains()` — now called by
scheduler.

### Methods NOT changed

- `load_tile_into_cache()` — stays as the "disk read" path. L2 check is in
  `get_tile()` before calling this.
- `prefetch_for_viewport()` — filters by L1 only. Tiles in L2 but not L1
  stay in the prefetch list and get promoted via `load_tile_for_prefetch()`.
- `prefetch_low_res_levels()` — gets L2 reads for free through
  `load_tile_for_prefetch()`.
- `lib.rs`, Python files — no changes.

### Tests to add

Need a test helper to create valid JPEG bytes (either `image` dev-dependency
or hardcoded minimal JPEG).

1. `test_get_tile_l2_hit` — insert valid compressed tile into L2, verify
   `get_tile()` returns decoded data and promotes to L1
2. `test_prefetch_l2_hit` — insert into L2, verify `load_tile_for_prefetch()`
   promotes to L1 without touching in-flight
3. `test_prefetch_l2_generation_guard` — stale generation with L2 hit returns None
4. `test_filter_cached_tiles_includes_l2` — L2-only tile appears in filter result
5. `test_filter_cached_tiles_no_slide` — slide_id=0 skips L2 check
6. `test_l2_decode_failure_falls_through` — corrupted L2 entry falls through to disk

### Risk

- **L1 hit path:** zero overhead (L1 check is still first)
- **L2 hit path:** ~2ms decode replaces ~5-10ms disk I/O (strictly faster)
- **L2 miss path:** one moka `get()` (~100ns) before falling through to disk
- **Concurrency:** all operations use atomics + moka concurrent access, no new locks
- **Stale data:** `SlideTileCoord` includes `slide_id`, cannot return wrong slide's tiles

### Verification gate

```
cd src/fastpath_core && cargo test
cd src/fastpath_core && cargo clippy -- -D warnings
uv run maturin develop --release --manifest-path src/fastpath_core/Cargo.toml
uv run python -m pytest tests/
```

**CRITICAL: Manual panning test**
1. Open a slide, pan around at various zoom levels
2. Compare perceived smoothness to Part 3 (before L2 reads)
3. If panning feels laggier, STOP and investigate before proceeding
4. Open same slide twice — second open should be faster (L2 warm)
5. Check `cache_stats()` — L2 hits should be nonzero on second open

---

## Part 5: Python Config + Constructor Update

**Goal:** Wire L2 parameters through Python config and app startup.

**Files:** `config.py`, `app.py`

- Replace `TILE_CACHE_SIZE_MB` with `L1_CACHE_SIZE_MB` (env: `FASTPATH_L1_CACHE_MB`, default 512)
- Add `L2_CACHE_SIZE_MB` (env: `FASTPATH_L2_CACHE_MB`, default 32768)
- Update `RustTileScheduler` construction in `app.py`
- Keep `PYTHON_TILE_CACHE_SIZE` for now (remove in Part 8)

---

## Part 6: SlidePool + Metadata Persistence

**Goal:** Avoid re-parsing `metadata.json` on slide revisit.

**Files:** New `slide_pool.rs`, modify `scheduler.rs`, `lib.rs`

- `SlidePool { slides: RwLock<HashMap<u64, SlideEntry>> }` with `load_or_get()`
- Replace `slide: RwLock<Option<SlideState>>` in scheduler
- If `with_slide()` RwLock is too slow: store active slide fields directly on
  scheduler, use pool only for load/switch

---

## Part 7: Bulk Preloader

**Goal:** Background preload all slides in a directory into L2.

**Files:** New `bulk_preload.rs`, modify `scheduler.rs`, `lib.rs`, `app.py`,
`navigator.py`

- Dedicated 3-thread rayon pool, reads JPEG tiles from disk into L2
- Priority order: starts from current slide index, expands outward (+-1, +-2, ...)
- Python: `app.py` calls `start_bulk_preload()` after navigator scan

---

## Part 8: Cleanup

**Goal:** Remove dead code, optimize FFI.

**Files:** `slide.py`, `config.py`, `lib.rs`

- Remove Python tile cache from `slide.py`
- Remove `PYTHON_TILE_CACHE_SIZE` from `config.py`
- Optional: `get_tile()` returns `Py<PyBytes>` instead of `Vec<u8>`

---

## Summary

| Part | Description                  | Status | Risk   | Files                 |
|------|------------------------------|--------|--------|-----------------------|
| 1    | Decoder split                | DONE   | Zero   | decoder.rs            |
| 2    | Compressed cache types       | DONE   | Zero   | cache.rs              |
| 3    | L2 write-through             | DONE   | Low    | scheduler.rs, lib.rs  |
| **4**| **L2 read path**             | **NOW**| Medium | scheduler.rs, cache.rs|
| 5    | Python config                | —      | Low    | config.py, app.py     |
| 6    | SlidePool + metadata persist | —      | Medium | slide_pool.rs, scheduler.rs |
| 7    | Bulk preloader               | —      | Medium | bulk_preload.rs, app.py |
| 8    | Cleanup + FFI opt            | —      | Low    | slide.py, config.py, lib.rs |

**Key principle:** After each part, run the full verification gate. If panning
feels laggier than the previous part, stop and bisect before proceeding.
