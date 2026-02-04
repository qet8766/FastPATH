# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

FastPATH is a pathology whole-slide image (WSI) viewer with a separate preprocessing CLI. Hybrid Python + QML + Rust. Requires Python >=3.11.

## Module Boundaries

The codebase has two independent workloads that share only data classes and a pyvips wrapper. **When working on one side, you can ignore the other.**

```
src/fastpath/
├── config.py          # Shared constants, env var overrides
├── core/
│   ├── types.py       # TileCoord, LevelInfo — shared data classes (no logic)
│   ├── slide.py       # SlideManager (metadata, viewport, level selection)
│   └── annotations.py # AnnotationManager (spatial indexing, GeoJSON)
├── preprocess/        # PREPROCESSING ONLY — standalone CLI
│   ├── pyramid.py     # VipsPyramidBuilder (pyvips dzsave)
│   ├── metadata.py    # PyramidMetadata, PyramidStatus, validation
│   ├── worker.py      # Batch worker (separate module for Windows mp compat)
│   └── backends.py    # pyvips wrapper (also used by viewer + AI)
├── ui/                # VIEWER ONLY
│   ├── app.py         # AppController — main entry, coordinates everything
│   ├── providers.py   # TileImageProvider (QML → Rust bridge)
│   ├── models.py      # TileModel, RecentFilesModel, FileListModel
│   └── qml/           # QML components (SlideViewer, TileLayer, Theme)
└── plugins/           # VIEWER ONLY
    ├── base.py        # Plugin / ModelPlugin ABCs
    ├── types.py       # PluginMetadata, PluginOutput, RegionOfInterest
    ├── registry.py    # PluginRegistry (discovery, registration)
    ├── executor.py    # PluginExecutor (worker thread, SlideContext bridge)
    ├── controller.py  # PluginController (QML facade)
    ├── context.py     # SlideContext (tile access for plugins)
    └── examples/      # Built-in demo plugins

src/fastpath_core/src/ (Rust, PyO3/maturin — VIEWER ONLY)
├── lib.rs             # PyO3 RustTileScheduler (Python-facing wrapper)
├── scheduler.rs       # TileScheduler (orchestrates cache + prefetch + dedup)
├── cache.rs           # moka tile cache (TinyLFU eviction)
├── prefetch.rs        # Viewport-based prefetching, rayon thread pool
├── format.rs          # SlideMetadata, TilePathResolver (.fastpath layout)
├── decoder.rs         # zune-jpeg SIMD JPEG decoding
└── error.rs           # TileError enum
```

### Cross-dependency summary

| Working on… | Read these | Safe to ignore |
|---|---|---|
| **Viewer (UI/rendering)** | `ui/`, `core/`, `plugins/`, `fastpath_core/`, `config.py` | `preprocess/` (only lazy-imported for in-app preprocessing) |
| **Preprocessing CLI** | `preprocess/`, `core/types.py`, `config.py` | `ui/`, `plugins/`, `core/slide.py`, `core/annotations.py`, `fastpath_core/` |
| **Rust tile scheduler** | `src/fastpath_core/src/` | All Python except `ui/app.py` and `ui/providers.py` (callers) |
| **Plugins** | `plugins/`, `preprocess/backends.py` | `preprocess/pyramid.py`, `preprocess/worker.py`, `fastpath_core/` |

### Communication between sides

The two sides communicate only through the filesystem: preprocessing writes `.fastpath` directories, the viewer reads them. No runtime imports cross the boundary (the viewer's lazy import of preprocessing is optional, for in-app preprocessing UX).

## Critical: Slide Loading Order

In `AppController.openSlide()` (`ui/app.py`), the load sequence matters:
```python
_rust_scheduler.load()         # 1. Load slide into Rust
prefetch_low_res_levels()      # 2. Fill cache BEFORE QML requests tiles
_slide_manager.load()          # 3. Emits slideLoaded → QML requests tiles
```
If SlideManager loads first, `slideLoaded` triggers QML tile requests before the cache is populated → gray tiles.

### Two-tier Rust cache architecture

Tile lookup order: **L1 → L2 → disk**.

1. **L1 — Rust moka** (4GB default) — decoded RGB tiles, concurrent TinyLFU eviction, cleared on slide switch
2. **L2 — Rust moka** (compressed JPEG bytes) — persists across slide switches, keyed by `SlideTileCoord` (includes `slide_id` hash). L2 hits decode JPEG (~2ms) and promote to L1, replacing ~5-10ms disk reads for previously-viewed slides

Every disk read writes through to L2 as a side effect. L2 is never cleared — tiles from different slides coexist via `slide_id` scoping. `filter_cached_tiles()` counts L2 entries as "available" for the cache miss threshold.

The `CACHE_MISS_THRESHOLD = 0.3` in `config.py` controls tile visibility: if >30% of visible tiles are uncached, all tiles render immediately (avoids prolonged gray screen at low zoom). A `_fallback_tile_model` shows previous-level tiles during zoom transitions.

### Rust concurrency: in-flight dedup & generation counter

`TileScheduler` has two concurrency mechanisms in `scheduler.rs`:

- **`in_flight: Mutex<HashSet<TileCoord>>`** — prevents duplicate decode work in **prefetch only**. Before decoding, a prefetch thread claims the coord; if already claimed, it returns `None` (skips). The lock is held only for the `HashSet` insert/remove, not during decode.
- **`generation: AtomicU64`** — monotonic counter bumped in `load()`/`close()` before clearing cache. Prefetch methods capture the generation before starting, then `load_tile_for_prefetch()` checks it at three points (before claiming, after claiming, after decode) to discard stale tiles from a previous slide. Memory ordering: `Release` on bump, `Acquire` on read.

`get_tile()` (user-facing) bypasses in-flight dedup entirely — explicit user requests always decode directly, even if a prefetch thread is concurrently decoding the same tile. This avoids returning `None` to QML, which would cache a placeholder permanently. Only background prefetch is generation-guarded and dedup-guarded.

## Preprocessing

Always **0.5 MPP** (20x equivalent), **JPEG Q80**, via pyvips `dzsave()`. These are hardcoded — not configurable.

- Layout: `tiles/level_N.pack` + `tiles/level_N.idx` (packed tiles) — level 0 = lowest resolution, level N = highest resolution
- Metadata includes `"tile_format": "pack_v2"`
- `getLevelForScale(scale)`: picks highest level where `downsample <= 1/scale`

CLI options: `--tile-size/-t` (64-2048, default 512), `--parallel-slides/-p` (default 3), `--force/-f` (rebuild). Input can be a single WSI file or a directory.

## Development Commands

```bash
uv sync                                                                    # Install deps
uv run maturin develop --release --manifest-path src/fastpath_core/Cargo.toml  # Build Rust (required, slow: LTO enabled)
uv run python -m fastpath                                                  # Run viewer
uv run python -m fastpath.preprocess <input.svs> -o <output_dir>           # Run preprocessing
uv run python -m pytest tests/                                             # All tests
uv run python -m pytest tests/test_annotations.py -k "test_name"           # Single test
cd src/fastpath_core && cargo test                                         # Rust tests
cd src/fastpath_core && cargo clippy -- -D warnings                        # Rust lint (must pass clean)
```

The Rust release build uses `lto = true` and `codegen-units = 1` for maximum optimization, which makes builds slow. For faster iteration during Rust development, temporarily remove these from `Cargo.toml` or use `maturin develop` without `--release`.

**IMPORTANT:** Always rebuild with `--release` after making Rust changes. Debug builds cause RAM explosion (system commit + physical memory) and severe performance degradation. Never leave a debug build installed for real usage.

## Code Conventions

- **Python**: PySide6 (not PyQt6), `pathlib.Path`, type hints throughout, build system is Hatchling
- **Rust**: PyO3 0.23 with `abi3-py311`, rayon for parallelism, parking_lot for locks, moka for caching, zune-jpeg for SIMD JPEG decoding, `bytes::Bytes` for zero-copy tile data
- **QML**: `Theme.qml` singleton for colors/fonts, Fusion style
- **Signals**: Qt signals for cross-component communication (`slideLoaded`, `errorOccurred`)
- **Testing**: Use `uv run python -m pytest` (not `uv run pytest`); use `mock_fastpath_dir` fixture for slide tests; Qt tests need a session-scoped `qapp` fixture (`QApplication` instance)

## Environment Variables

All overridable in `config.py`:

| Variable | Default | Description |
|---|---|---|
| `FASTPATH_VIPS_PATH` | `C:/vips` | Base path for VIPS installation |
| `FASTPATH_L1_CACHE_MB` | `4096` | Rust L1 tile cache size in MB (decoded RGB) |
| `FASTPATH_L2_CACHE_MB` | `32768` | Rust L2 compressed cache size in MB (JPEG bytes) |
| `FASTPATH_PREFETCH_DISTANCE` | `3` | Tiles to prefetch ahead |
| `FASTPATH_VIPS_CONCURRENCY` | `24` | VIPS internal thread count |
| `FASTPATH_TILE_TIMING` | unset | Set to `1` for per-tile disk/decode/total timing on stderr |

## Windows Notes

- VIPS/OpenSlide DLLs expected at `C:/vips/vips-dev-*/bin/` (auto-loaded in `fastpath/__init__.py`)
- Also loads `vips-modules-8.18/` — this path is hardcoded and must be updated if VIPS version changes
- System libvips required (not `pyvips-binary`); install from https://github.com/libvips/build-win64-mxe/releases (the "all" variant)
- `preprocess/worker.py` exists as a separate module because Windows multiprocessing requires worker functions to be importable (can't be in `__main__`)

## Debugging

- **Gray tiles at load**: Check load order in `openSlide()` — prefetch must complete before `slideLoaded`
- **Wrong tiles**: Check `getLevelForScale()` — verify level matches zoom
- **Tile decode errors**: Rust logs `[TILE ERROR]` to stderr
- **Prefetch stats**: `[PREFETCH] Loading N tiles...` / `[PREFETCH] Done: X loaded, Y failed` in stderr
- **Race conditions**: `AppController._loading_lock` prevents concurrent slide loads
- **L2 cache verification**: `cache_stats()` — L2 hits should be nonzero when reopening a previously-viewed slide
- **Per-tile timing**: Set `FASTPATH_TILE_TIMING=1` for `[TILE TIMING]` lines on stderr showing disk/L2/decode/total breakdowns

## Git Worktree Workflow

This project uses git worktrees for parallel feature development. Each feature branch gets its own working directory with independent `.venv` and Rust build artifacts.

### Branch naming

- `feature/<name>` — new functionality
- `fix/<name>` — bug fixes
- `infra/<name>` — tooling, CI, build changes

### Worktree scripts

```powershell
.\scripts\new-worktree.ps1 -Branch feature/annotations           # Full release build
.\scripts\new-worktree.ps1 -Branch feature/ui-polish -Fast        # Fast Rust build (no LTO)
.\scripts\remove-worktree.ps1 -Branch feature/annotations         # Clean up
.\scripts\remove-worktree.ps1 -Branch feature/test -DeleteBranch  # Clean up + delete branch
```

Worktrees are created at `C:\chest\projects\FastPATH-wt-<branch-slug>\` (sibling directories).

### Rust build profiles

- `--release` — full LTO, slow build, maximum performance (production)
- `--profile dev-fast` — opt-level 2, no LTO, fast build (feature branches that don't touch Rust)

### Merge strategy

1. Rebase onto master, fast-forward merge
2. Recommended merge order (minimizes conflicts):
   1. `feature/preprocessing` — isolated module, zero conflict risk
   2. `feature/rust-performance` — isolated module, zero conflict risk
   3. `feature/frontend-ui` — minimal `main.qml` touch
   4. `feature/annotations` — `InteractionLayer` + sidebar + menu
   5. `feature/ai-plugins` — `InteractionLayer` + sidebar + `app.py` (last, rebases on annotation changes)

### Modular QML architecture

Sidebar panels are extracted into individual components (`SlideInfoPanel`, `OverviewPanel`, `ViewControlsPanel`, `NavigationPanel`). Feature branches add new panels as single-line additions to the `ColumnLayout` in `main.qml`'s sidebar — these merge cleanly across branches.

`InteractionLayer.qml` in `SlideViewer.qml` is a mode-based overlay (`"none"`, `"draw"`, `"roi"`, `"measure"`). Feature branches extend it by adding handlers for their specific modes in separate code sections.
