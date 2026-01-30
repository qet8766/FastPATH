# CLAUDE.md

FastPATH is a pathology whole-slide image (WSI) viewer with a separate preprocessing CLI. Hybrid Python + QML + Rust.

## Module Boundaries

The codebase has two independent workloads that share only data classes and a pyvips wrapper. **When working on one side, you can ignore the other.**

```
src/fastpath/
├── config.py          # Shared constants (both sides)
├── core/
│   ├── types.py       # TileCoord, LevelInfo (shared data classes, no logic)
│   ├── slide.py       # VIEWER: SlideManager (metadata, viewport, getLevelForScale)
│   ├── annotations.py # VIEWER: AnnotationManager (spatial indexing)
│   └── project.py     # VIEWER: ProjectManager
├── preprocess/        # PREPROCESSING ONLY (standalone CLI)
│   ├── pyramid.py     # VipsPyramidBuilder (pyvips dzsave)
│   ├── worker.py      # Batch processing worker
│   ├── backends.py    # pyvips wrapper (also used by core/slide.py, ai/manager.py)
│   └── __main__.py    # CLI entry point
├── ui/                # VIEWER ONLY
│   ├── app.py         # AppController (main entry, coordinates everything)
│   ├── providers.py   # TileImageProvider (QML → Rust bridge)
│   ├── models.py      # TileModel, RecentFilesModel, FileListModel
│   ├── navigator.py   # SlideNavigator
│   ├── settings.py    # Settings
│   └── qml/           # QML components (SlideViewer, TileLayer, Theme, etc.)
└── ai/                # VIEWER ONLY
    ├── base.py        # AIPlugin ABC — inherit for custom plugins
    └── manager.py     # AIPluginManager

src/fastpath_core/     # Rust extension (VIEWER ONLY) — PyO3/maturin
└── src/
    ├── scheduler.rs   # RustTileScheduler (caching, prefetching)
    ├── cache.rs, prefetch.rs, decoder.rs, format.rs, error.rs, lib.rs
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

## Preprocessing

Always **0.5 MPP** (20x equivalent), **JPEG Q80**, via pyvips `dzsave()`. These are hardcoded — not configurable.

- Layout: `tiles_files/N/col_row.jpg` — level 0 = lowest resolution (inverted from viewer convention)
- Metadata includes `"tile_format": "dzsave"`; the Rust scheduler handles level inversion transparently
- `getLevelForScale(scale)`: picks highest level where `downsample <= 1/scale`

## Development Commands

```bash
uv sync                                                                    # Install deps
uv run maturin develop --release --manifest-path src/fastpath_core/Cargo.toml  # Build Rust (required)
uv run python -m fastpath                                                  # Run viewer
uv run python -m fastpath.preprocess <input.svs> -o <output_dir>           # Run preprocessing
uv run python -m pytest tests/                                             # All tests
uv run python -m pytest tests/test_annotations.py -k "test_name"           # Single test
cd src/fastpath_core && cargo test                                         # Rust tests
```

## Code Conventions

- **Python**: PySide6 (not PyQt6), `pathlib.Path`, type hints throughout
- **Rust**: PyO3/maturin, rayon for parallelism, parking_lot for locks, crossbeam for channels
- **QML**: `Theme.qml` singleton for colors/fonts, Fusion style
- **Signals**: Qt signals for cross-component communication (`slideLoaded`, `errorOccurred`)
- **Testing**: Use `uv run python -m pytest` (not `uv run pytest`); use `mock_fastpath_dir` fixture for slide tests

## Performance Defaults

- Tile cache: 12GB (`TILE_CACHE_SIZE_MB`), Prefetch distance: 3 tiles (`PREFETCH_DISTANCE`) — see `config.py`
- Preprocessing: `VIPS_CONCURRENCY=8`, `VIPS_DISC_THRESHOLD=3GB`, `-p 3` parallel slides — set in `preprocess/__main__.py`

## Windows Notes

- VIPS/OpenSlide DLLs expected at `C:/vips/vips-dev-*/bin/` (auto-loaded in `fastpath/__init__.py`)

## Debugging

- **Gray tiles at load**: Check load order in `openSlide()` — prefetch must complete before `slideLoaded`
- **Wrong tiles**: Check `getLevelForScale()` — verify level matches zoom
- **Tile decode errors**: Rust logs `[TILE ERROR]` to stderr
- **Prefetch stats**: `[PREFETCH] Loading N tiles...` / `[PREFETCH] Done: X loaded, Y failed` in stderr
- **Race conditions**: `AppController._loading_lock` prevents concurrent slide loads
