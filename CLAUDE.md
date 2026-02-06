# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

FastPATH is a pathology whole-slide image (WSI) viewer with a separate preprocessing CLI. Python + QML + Rust. Requires Python >=3.11.

The web viewer/server lives in a separate repo on WSL: `\\wsl.localhost\Ubuntu-22.04\home\eteriny\projects\FastPATH_server`. It reads the same `.fastpath` directories produced by preprocessing.

## Module Boundaries

Two independent workloads share only data classes (`types.py`) and a pyvips wrapper (`preprocess/backends.py`). They communicate through the filesystem: preprocessing writes `.fastpath` directories, the viewer reads them. **When working on one side, ignore the other.**

- `src/fastpath/types.py` — shared data classes (used by preprocess, plugins, and viewer)
- `src/fastpath/preprocess/` — standalone preprocessing CLI (pyvips dzsave)
- `src/fastpath/ui/` + `src/fastpath/plugins/` — desktop viewer (PySide6/QML)
- `src/fastpath_core/src/` — Rust tile scheduler (PyO3/maturin)

| Working on… | Read these | Safe to ignore |
|---|---|---|
| **Desktop viewer** | `ui/`, `plugins/`, `fastpath_core/`, `types.py`, `config.py` | `preprocess/` |
| **Preprocessing CLI** | `preprocess/`, `types.py`, `config.py` | `ui/`, `plugins/`, `fastpath_core/` |
| **Rust tile scheduler** | `src/fastpath_core/src/` | All Python except `ui/app.py` and `ui/providers.py` |
| **Plugins** | `plugins/`, `types.py`, `preprocess/backends.py` | `preprocess/pyramid.py`, `preprocess/worker.py`, `fastpath_core/` |

## Critical: Slide Loading Order

In `AppController.openSlide()` (`ui/app.py`), order matters:
```python
_rust_scheduler.load()         # 1. Load slide into Rust
prefetch_low_res_levels()      # 2. Fill cache BEFORE QML requests tiles
_slide_manager.load()          # 3. Emits slideLoaded → QML requests tiles
```
If step 3 fires before step 2, QML requests tiles before cache is populated → gray tiles.

## Tile Cache

Lookup order: **L1 → L2 → disk**. L1 (moka, 4GB, decoded RGB) is cleared on slide switch. L2 (moka, compressed JPEG bytes) persists across slides, keyed by `slide_id`. Every disk read writes through to L2. `CACHE_MISS_THRESHOLD = 0.3` in `config.py`: if >30% of visible tiles are uncached, all tiles render immediately to avoid gray screens.

## Preprocessing

Always **0.5 MPP** (20x), **JPEG Q80**, hardcoded. Layout: `tiles/level_N.pack` + `tiles/level_N.idx` (pack_v2 format). Level 0 = lowest resolution. CLI options: `--tile-size/-t` (default 512), `--parallel-slides/-p` (default 3), `--force/-f`.

## Development Commands

```bash
# Setup & build
uv sync
uv run maturin develop --release --manifest-path src/fastpath_core/Cargo.toml

# Run
uv run python -m fastpath                                              # Desktop viewer
uv run python -m fastpath.preprocess <input.svs> -o <output_dir>       # Preprocessing

# Testing
uv run python -m pytest tests/                                         # Python tests
uv run python -m pytest tests/test_annotations.py -k "test_name"       # Single test
cd src/fastpath_core && cargo test                                     # Rust tests
cd src/fastpath_core && cargo clippy -- -D warnings                    # Rust lint (must pass)
```

For faster Rust iteration: `--profile dev-fast` instead of `--release` (opt-level 2, no LTO). **Always rebuild with `--release` after Rust changes** — debug builds cause RAM explosion.

## Code Conventions

- **Python**: PySide6 (not PyQt6), `pathlib.Path`, type hints, Hatchling build
- **Rust**: PyO3 0.23 `abi3-py311`, rayon, parking_lot, moka, zune-jpeg, `bytes::Bytes`
- **QML**: `Theme.qml` singleton for colors/fonts, Fusion style
- **Testing**: `uv run python -m pytest` (not `uv run pytest`); `mock_fastpath_dir` fixture for slide tests; Qt tests need session-scoped `qapp` fixture

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `FASTPATH_VIPS_PATH` | `C:/vips` | VIPS installation path |
| `FASTPATH_L1_CACHE_MB` | `4096` | L1 tile cache (decoded RGB) |
| `FASTPATH_L2_CACHE_MB` | `32768` | L2 compressed cache (JPEG bytes) |
| `FASTPATH_PREFETCH_DISTANCE` | `3` | Tiles to prefetch ahead |
| `FASTPATH_TILE_TIMING` | unset | `1` for per-tile timing on stderr |

## Windows Notes

- System libvips required at `C:/vips/vips-dev-*/bin/` (auto-loaded in `__init__.py`). Install "all" variant from libvips releases.
- `preprocess/worker.py` is a separate module because Windows multiprocessing requires importable worker functions.

## Debugging

- **Gray tiles at load**: Check load order in `openSlide()` — prefetch must complete before `slideLoaded`
- **Wrong tiles**: Check `getLevelForScale()` — verify level matches zoom
- **Tile errors**: Rust logs `[TILE ERROR]` to stderr; set `FASTPATH_TILE_TIMING=1` for timing breakdowns
- **Race conditions**: `AppController._loading_lock` prevents concurrent slide loads
- **L2 cache**: `cache_stats()` — L2 hits should be nonzero when reopening a previously-viewed slide

## Git Conventions

- Branches: `feature/<name>`, `fix/<name>`, `infra/<name>`
- Merge strategy: rebase onto master, fast-forward merge
