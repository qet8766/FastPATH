# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

FastPATH is a pathology whole-slide image (WSI) viewer with a separate preprocessing CLI. Hybrid Python + QML + Rust. Requires Python >=3.11.

## Module Boundaries

The codebase has two independent workloads that share only data classes and a pyvips wrapper. **When working on one side, you can ignore the other.**

```
src/fastpath/
├── config.py          # Shared constants (both sides), env var overrides
├── core/
│   ├── types.py       # TileCoord (NamedTuple), LevelInfo (dataclass) — no logic
│   ├── slide.py       # VIEWER: SlideManager (metadata, viewport, getLevelForScale)
│   ├── annotations.py # VIEWER: AnnotationManager (spatial indexing)
│   └── project.py     # VIEWER: ProjectManager
├── preprocess/        # PREPROCESSING ONLY (standalone CLI)
│   ├── pyramid.py     # VipsPyramidBuilder (pyvips dzsave)
│   ├── metadata.py    # PyramidMetadata dataclass, PyramidStatus enum, validation
│   ├── worker.py      # Batch worker (separate module for Windows multiprocessing compat)
│   ├── backends.py    # pyvips wrapper (also used by core/slide.py, ai/manager.py)
│   └── __main__.py    # CLI entry point
├── ui/                # VIEWER ONLY
│   ├── app.py         # AppController (main entry, coordinates everything)
│   ├── providers.py   # TileImageProvider (QML → Rust bridge)
│   ├── models.py      # TileModel, RecentFilesModel, FileListModel
│   ├── navigator.py   # SlideNavigator
│   ├── preprocess.py  # PreprocessController (in-app preprocessing UI)
│   ├── settings.py    # Settings (QSettings wrapper)
│   └── qml/           # QML components (SlideViewer, TileLayer, Theme, etc.)
└── ai/                # VIEWER ONLY
    ├── base.py        # AIPlugin ABC — inherit for custom plugins
    └── manager.py     # AIPluginManager (discovery, loading, PluginWorker thread)

src/fastpath_core/     # Rust extension (VIEWER ONLY) — PyO3/maturin
└── src/
    ├── scheduler.rs   # RustTileScheduler (caching, prefetching)
    ├── cache.rs       # DashMap tile cache + Mutex VecDeque LRU eviction
    ├── prefetch.rs    # Background thread, crossbeam channel, rayon thread pool
    ├── decoder.rs     # zune-jpeg SIMD-accelerated JPEG decoding
    ├── format.rs, error.rs, lib.rs
```

### Cross-dependency summary

| Working on… | Read these | Safe to ignore |
|---|---|---|
| **Viewer (UI/rendering)** | `ui/`, `core/`, `ai/`, `fastpath_core/`, `config.py` | `preprocess/` (only lazy-imported for in-app preprocessing) |
| **Preprocessing CLI** | `preprocess/`, `core/types.py`, `config.py` | `ui/`, `ai/`, `core/slide.py`, `core/annotations.py`, `fastpath_core/` |
| **Rust tile scheduler** | `src/fastpath_core/src/` | All Python except `ui/app.py` and `ui/providers.py` (callers) |
| **AI plugins** | `ai/`, `core/slide.py`, `preprocess/backends.py` | `preprocess/pyramid.py`, `preprocess/worker.py`, `fastpath_core/` |

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

### Dual-cache architecture

Tiles are cached in two layers:
1. **Rust DashMap** (12GB default) — primary cache, lock-free concurrent, LRU eviction via `VecDeque`
2. **Python OrderedDict** (256 tiles default) — secondary LRU in `SlideManager`, keyed by `TileCoord`

The `CACHE_MISS_THRESHOLD = 0.3` in `app.py` controls tile visibility: if >30% of visible tiles are uncached, all tiles render immediately (avoids prolonged gray screen at low zoom). A `_fallback_tile_model` shows previous-level tiles during zoom transitions.

## Preprocessing

Always **0.5 MPP** (20x equivalent), **JPEG Q80**, via pyvips `dzsave()`. These are hardcoded — not configurable.

- Layout: `tiles_files/N/col_row.jpg` — level 0 = lowest resolution, level N = highest resolution
- Metadata includes `"tile_format": "dzsave"`
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
```

The Rust release build uses `lto = true` and `codegen-units = 1` for maximum optimization, which makes builds slow. For faster iteration during Rust development, temporarily remove these from `Cargo.toml` or use `maturin develop` without `--release`.

## Code Conventions

- **Python**: PySide6 (not PyQt6), `pathlib.Path`, type hints throughout, build system is Hatchling
- **Rust**: PyO3 0.23 with `abi3-py311`, rayon for parallelism, parking_lot for locks, crossbeam for channels, `bytes::Bytes` for zero-copy tile data
- **QML**: `Theme.qml` singleton for colors/fonts, Fusion style
- **Signals**: Qt signals for cross-component communication (`slideLoaded`, `errorOccurred`)
- **Testing**: Use `uv run python -m pytest` (not `uv run pytest`); use `mock_fastpath_dir` fixture for slide tests; Qt tests need a session-scoped `qapp` fixture (`QApplication` instance)

## Environment Variables

All overridable in `config.py`:

| Variable | Default | Description |
|---|---|---|
| `FASTPATH_VIPS_PATH` | `C:/vips` | Base path for VIPS installation |
| `FASTPATH_TILE_CACHE_MB` | `12288` | Rust tile cache size (MB) |
| `FASTPATH_PREFETCH_DISTANCE` | `3` | Tiles to prefetch ahead |
| `FASTPATH_PYTHON_CACHE_SIZE` | `256` | Python-side LRU cache (tiles) |
| `FASTPATH_VIPS_CONCURRENCY` | `8` | VIPS internal thread count |

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
