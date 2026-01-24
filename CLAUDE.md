# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

FastPATH is an extensible pathology whole-slide image (WSI) viewer. It preprocesses large WSI files into tiled pyramids (`.fastpath` directories), then displays them with pan/zoom, annotations, and AI plugin support.

## Architecture

**Hybrid Python + Rust design:**

| Layer | Language | Purpose |
|-------|----------|---------|
| UI & App Logic | Python + QML | Views, controllers, AI plugins |
| Tile Scheduler | Rust | High-performance tile loading with caching and prefetching |
| Preprocessing | Python (pyvips) | WSI → .fastpath pyramid conversion via dzsave |

### Data Flow

```
User pans/zooms → QML SlideViewer → AppController.updateViewportWithVelocity()
                                            ↓
                      RustTileScheduler.update_viewport() → triggers prefetch
                                            ↓
                      TileModel.batchUpdate() → QML TileLayer renders (atomic)
                                            ↓
                      Image requests → TileImageProvider → RustTileScheduler.get_tile()
```

### Critical: Slide Loading Order

In `AppController.openSlide()`, the load sequence is critical:
```python
_rust_scheduler.load()         # 1. Load slide into Rust
prefetch_low_res_levels()      # 2. Fill cache BEFORE QML requests tiles
_slide_manager.load()          # 3. Emits slideLoaded → QML requests tiles
```
If SlideManager loads first, its `slideLoaded` signal triggers QML to request tiles before the cache is populated, causing gray tiles.

### Module Structure

```
src/fastpath/
├── core/           # SlideManager, AnnotationManager (metadata, spatial indexing)
├── preprocess/     # VipsPyramidBuilder (pyvips dzsave-based)
├── ui/             # AppController, TileModel, QML providers
│   └── qml/        # QML components (SlideViewer, TileLayer, Theme)
└── ai/             # AIPlugin ABC, PluginManager

src/fastpath_core/  # Rust extension (PyO3/maturin) - RustTileScheduler
```

### Tile Format

Preprocessing uses pyvips `dzsave()` which creates the **dzsave format**:
- `tiles_files/N/col_row.jpg` where level 0 = lowest resolution (inverted from FastPATH convention)
- Metadata includes `"tile_format": "dzsave"` to indicate this layout
- The Rust scheduler handles the level inversion transparently

### Level Selection

`SlideManager.getLevelForScale(scale)` picks the pyramid level:
- `target_downsample = 1/scale` (e.g., 4% zoom → downsample 25)
- Picks highest level where `downsample <= target` (prefers sharper tiles)
- Initial view typically uses level 3-5 depending on slide size and window dimensions

## Development Commands

```bash
# Install dependencies
uv sync

# Build Rust extension (required before running app)
# On Windows, ensure cargo is in PATH first
uv run maturin develop --release --manifest-path src/fastpath_core/Cargo.toml

# Run the app (or use: fastpath)
uv run python -m fastpath

# Run preprocessing CLI (or use: fastpath-preprocess)
uv run python -m fastpath.preprocess <input.svs> -o <output_dir>

# Run all tests
uv run python -m pytest tests/

# Run a single test
uv run python -m pytest tests/test_annotations.py -k "test_name"

# Run Rust tests (ensure cargo is in PATH)
cd src/fastpath_core && cargo test

# Run viewer with example slide (after preprocessing)
uv run python -m fastpath "output/example 1.fastpath"
```

## Key Files

| File | Purpose |
|------|---------|
| `src/fastpath/ui/app.py` | AppController - main entry point, coordinates SlideManager and RustTileScheduler |
| `src/fastpath/core/slide.py` | SlideManager - metadata, viewport calculations, `getLevelForScale()` |
| `src/fastpath/ui/providers.py` | TileImageProvider - bridges QML image requests to Rust scheduler |
| `src/fastpath_core/src/scheduler.rs` | Rust tile scheduler - caching, prefetching, `prefetch_low_res_levels()` |
| `src/fastpath/preprocess/pyramid.py` | VipsPyramidBuilder for WSI → .fastpath conversion |
| `src/fastpath/ai/base.py` | AIPlugin ABC - inherit for custom plugins |
| `tests/conftest.py` | Pytest fixtures including `mock_fastpath_dir` (creates dzsave-format test slides) |

## Code Conventions

- **Python**: PySide6 (not PyQt6), `pathlib.Path` for file paths, type hints throughout
- **Rust**: PyO3/maturin for Python bindings, rayon for parallelism, parking_lot for locks, crossbeam for channels
- **QML**: Use `Theme.qml` singleton for colors/fonts, Fusion style for cross-platform consistency
- **Signals**: Use Qt signals for cross-component communication (e.g., `slideLoaded`, `errorOccurred`)

## Testing

- Use `uv run python -m pytest` (not `uv run pytest`) to ensure correct module resolution
- Use `mock_fastpath_dir` fixture for slide loading tests (creates dzsave-format tiles)

## Performance Defaults

- **Tile cache**: 12GB, **Prefetch distance**: 3 tiles ahead
- Preprocessing: `VIPS_CONCURRENCY=8`, `VIPS_DISC_THRESHOLD=3GB`, `-p 3` (parallel slides) - set automatically in `preprocess/__main__.py`

## Windows Notes

- VIPS and OpenSlide DLLs expected at `C:/vips/vips-dev-*/bin/` (handled automatically in `fastpath/__init__.py`)

## Debugging Tips

- **Gray tiles at load**: Check load order in `openSlide()` - prefetch must complete before `slideLoaded` signal
- **Wrong tiles displayed**: Check `getLevelForScale()` - verify the level matches expected zoom
- **Tile decode errors**: Rust scheduler logs `[TILE ERROR]` to stderr with path and error details
- **Prefetch stats**: Watch for `[PREFETCH] Loading N tiles...` and `[PREFETCH] Done: X loaded, Y failed` in stderr
- **Visual verification**: Use PIL's `ImageGrab.grab()` to capture screenshots during testing
- **Race conditions**: AppController uses `_loading_lock` to prevent concurrent slide loads
