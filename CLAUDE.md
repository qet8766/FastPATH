# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

FastPATH is a pathology whole-slide image (WSI) viewer with a separate preprocessing CLI and a web viewer. Hybrid Python + QML + Rust (desktop), React + TypeScript + WebGPU (web). Requires Python >=3.11.

## Module Boundaries

The codebase has three independent workloads that share only data classes and a pyvips wrapper. **When working on one side, you can ignore the others.**

```
src/fastpath/
├── config.py          # Shared constants, env var overrides
├── core/
│   ├── types.py       # TileCoord, LevelInfo — shared data classes (no logic)
│   ├── slide.py       # SlideManager (metadata, viewport, level selection)
│   ├── annotations.py # AnnotationManager (spatial indexing, GeoJSON)
│   ├── paths.py       # Path utilities (QML URL → filesystem, atomic JSON save)
│   └── project.py     # ProjectManager (.fpproj files — slide path, annotations, view state)
├── preprocess/        # PREPROCESSING ONLY — standalone CLI
│   ├── pyramid.py     # VipsPyramidBuilder (pyvips dzsave)
│   ├── metadata.py    # PyramidMetadata, PyramidStatus, validation
│   ├── worker.py      # Batch worker (separate module for Windows mp compat)
│   └── backends.py    # pyvips wrapper (also used by viewer + plugins)
├── ui/                # DESKTOP VIEWER ONLY
│   ├── app.py         # AppController — main entry, coordinates everything
│   ├── providers.py   # TileImageProvider (QML → Rust bridge)
│   ├── models.py      # TileModel, RecentFilesModel, FileListModel
│   ├── navigator.py   # SlideNavigator (multi-slide directory navigation)
│   ├── settings.py    # QSettings wrapper (persistent viewer/preprocessing prefs)
│   ├── preprocess.py  # In-app preprocessing UI controller
│   └── qml/           # QML components (SlideViewer, TileLayer, Theme, panels)
└── plugins/           # DESKTOP VIEWER ONLY
    ├── base.py        # Plugin / ModelPlugin ABCs
    ├── types.py       # PluginMetadata, PluginOutput, RegionOfInterest
    ├── registry.py    # PluginRegistry (discovery, registration)
    ├── executor.py    # PluginExecutor (worker thread, SlideContext bridge)
    ├── controller.py  # PluginController (QML facade)
    ├── context.py     # SlideContext (tile access for plugins)
    ├── examples/      # Built-in demo plugins
    └── nulite/        # Nucleus segmentation plugin (FastViT model)

src/fastpath_core/src/ (Rust, PyO3/maturin — DESKTOP VIEWER ONLY)
├── lib.rs             # PyO3 RustTileScheduler (Python-facing wrapper)
├── scheduler.rs       # TileScheduler (orchestrates cache + prefetch + dedup)
├── cache.rs           # moka tile cache (TinyLFU eviction)
├── prefetch.rs        # Viewport-based prefetching, rayon thread pool
├── format.rs          # SlideMetadata, TilePathResolver (.fastpath layout)
├── decoder.rs         # zune-jpeg SIMD JPEG decoding
├── pack.rs            # Packed tile reader (pack_v2 format: .pack + .idx files)
├── bulk_preload.rs    # Background L2 cache preloader (dedicated 3-thread rayon pool)
├── slide_pool.rs      # Metadata pool — caches SlideEntry by slide_id
├── tile_buffer.rs     # Tile buffer management
├── tile_reader.rs     # Tile reading abstractions
├── test_utils.rs      # Test utilities
└── error.rs           # TileError enum

web/                   # WEB VIEWER — fully independent from desktop viewer
├── server/            # FastAPI backend (slide discovery, pack/idx serving with Range requests)
│   ├── main.py        # FastAPI app, CORS, static file serving
│   ├── routes/slides.py  # Slide indexing and metadata endpoints
│   ├── config.py      # ServerConfig (env vars for slide dirs, host, port)
│   └── static_files.py   # Range request support for .pack/.idx files
├── client/            # React + TypeScript + Vite + WebGPU frontend
│   └── src/
│       ├── renderer/  # WebGPU renderer, texture atlas, WGSL shaders
│       ├── scheduler/ # Tile scheduling (mirrors Rust scheduler logic)
│       ├── network/   # Pack v2 network layer (Range requests for tile data)
│       ├── workers/   # Decode web workers
│       ├── viewer/    # Viewer component and input handling
│       └── cache/     # Browser-side tile cache
└── tests/             # Server (pytest) + client (vitest) tests
```

### Cross-dependency summary

| Working on… | Read these | Safe to ignore |
|---|---|---|
| **Desktop viewer (UI/rendering)** | `ui/`, `core/`, `plugins/`, `fastpath_core/`, `config.py` | `preprocess/` (only lazy-imported for in-app preprocessing), `web/` |
| **Preprocessing CLI** | `preprocess/`, `core/types.py`, `config.py` | `ui/`, `plugins/`, `core/slide.py`, `core/annotations.py`, `fastpath_core/`, `web/` |
| **Rust tile scheduler** | `src/fastpath_core/src/` | All Python except `ui/app.py` and `ui/providers.py` (callers), `web/` |
| **Plugins** | `plugins/`, `preprocess/backends.py` | `preprocess/pyramid.py`, `preprocess/worker.py`, `fastpath_core/`, `web/` |
| **Web viewer** | `web/` | All of `src/` (web reads `.fastpath` dirs from disk, no Python imports) |

### Communication between sides

All three sides communicate only through the filesystem: preprocessing writes `.fastpath` directories, the desktop viewer and web server read them. No runtime imports cross boundaries (the desktop viewer's lazy import of preprocessing is optional, for in-app preprocessing UX).

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
# Setup & build
uv sync                                                                    # Install deps
uv run maturin develop --release --manifest-path src/fastpath_core/Cargo.toml  # Build Rust (required, slow: LTO enabled)

# Desktop viewer
uv run python -m fastpath                                                  # Run viewer
uv run python -m fastpath.preprocess <input.svs> -o <output_dir>           # Run preprocessing

# Web viewer (server + client run separately)
# Generate SSL certs (one-time):
openssl req -x509 -newkey rsa:4096 -keyout web/server/certs/key.pem -out web/server/certs/cert.pem -days 365 -nodes -subj "/CN=localhost" -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"
$env:FASTPATH_WEB_SLIDE_DIRS="C:\path\to\slides"                          # Point to .fastpath dirs
uv run --group dev python -m web.server.main                               # Hypercorn HTTPS server at :8000 (HTTP/3)
$env:VITE_FASTPATH_API_BASE="https://127.0.0.1:8000"                      # Client needs API base (HTTPS)
cd web/client && npm install && npm run dev                                # Vite dev server at :5173

# Testing
uv run python -m pytest tests/                                             # Python tests (desktop)
uv run python -m pytest web/tests/                                         # Python tests (web server)
uv run python -m pytest tests/test_annotations.py -k "test_name"           # Single test
cd web/client && npm test                                                  # Web client tests (vitest)
cd src/fastpath_core && cargo test                                         # Rust tests
cd src/fastpath_core && cargo clippy -- -D warnings                        # Rust lint (must pass clean)
```

The Rust release build uses `lto = true` and `codegen-units = 1` for maximum optimization, which makes builds slow. For faster iteration, use `--profile dev-fast` (opt-level 2, no LTO): `uv run maturin develop --profile dev-fast --manifest-path src/fastpath_core/Cargo.toml`.

**IMPORTANT:** Always rebuild with `--release` after making Rust changes. Debug builds cause RAM explosion (system commit + physical memory) and severe performance degradation. Never leave a debug build installed for real usage.

## Code Conventions

- **Python**: PySide6 (not PyQt6), `pathlib.Path`, type hints throughout, build system is Hatchling
- **Rust**: PyO3 0.23 with `abi3-py311`, rayon for parallelism, parking_lot for locks, moka for caching, zune-jpeg for SIMD JPEG decoding, `bytes::Bytes` for zero-copy tile data
- **QML**: `Theme.qml` singleton for colors/fonts, Fusion style
- **Signals**: Qt signals for cross-component communication (`slideLoaded`, `errorOccurred`)
- **Testing**: Use `uv run python -m pytest` (not `uv run pytest`); use `mock_fastpath_dir` fixture for slide tests; Qt tests need a session-scoped `qapp` fixture (`QApplication` instance)

## Environment Variables

Desktop viewer — all overridable in `config.py`:

| Variable | Default | Description |
|---|---|---|
| `FASTPATH_VIPS_PATH` | `C:/vips` | Base path for VIPS installation |
| `FASTPATH_L1_CACHE_MB` | `4096` | Rust L1 tile cache size in MB (decoded RGB) |
| `FASTPATH_L2_CACHE_MB` | `32768` | Rust L2 compressed cache size in MB (JPEG bytes) |
| `FASTPATH_PREFETCH_DISTANCE` | `3` | Tiles to prefetch ahead |
| `FASTPATH_VIPS_CONCURRENCY` | `24` | VIPS internal thread count |
| `FASTPATH_TILE_TIMING` | unset | Set to `1` for per-tile disk/decode/total timing on stderr |

Web viewer — in `web/server/config.py`:

| Variable | Default | Description |
|---|---|---|
| `FASTPATH_WEB_SLIDE_DIRS` | cwd | Semicolon-separated paths to directories containing `.fastpath` dirs |
| `FASTPATH_WEB_HOST` | `127.0.0.1` | Web server bind host |
| `FASTPATH_WEB_PORT` | `8000` | Web server bind port |
| `FASTPATH_WEB_SSL_CERTFILE` | `web/server/certs/cert.pem` | Path to SSL certificate |
| `FASTPATH_WEB_SSL_KEYFILE` | `web/server/certs/key.pem` | Path to SSL private key |
| `VITE_FASTPATH_API_BASE` | — | Client-side: API base URL (must be set for dev, e.g. `https://127.0.0.1:8000`) |

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

## Git Conventions

### Branch naming

- `feature/<name>` — new functionality
- `fix/<name>` — bug fixes
- `infra/<name>` — tooling, CI, build changes

### Merge strategy

Rebase onto master, fast-forward merge.

### Rust build profiles

- `--release` — full LTO, slow build, maximum performance (production)
- `--profile dev-fast` — opt-level 2, no LTO, fast build (feature branches that don't touch Rust)

### Modular QML architecture

Sidebar panels are extracted into individual components (`SlideInfoPanel`, `OverviewPanel`, `ViewControlsPanel`, `NavigationPanel`). New panels are added as single-line additions to the `ColumnLayout` in `main.qml`'s sidebar.

`InteractionLayer.qml` in `SlideViewer.qml` is a mode-based overlay (`"none"`, `"draw"`, `"roi"`, `"measure"`). New modes are added by extending handlers in separate code sections.

## Web Viewer Architecture

The web viewer is a separate stack that reads the same `.fastpath` directories produced by preprocessing. It does not import any Python from the desktop viewer.

- **Server**: FastAPI + Hypercorn serves slide metadata (`/api/slides`, `/api/slides/<hash>/metadata`) and tile data via HTTP Range requests on `.pack`/`.idx` files. **HTTP/3 (QUIC)** is enabled when SSL certs are present, eliminating HTTP/1.1's 6-connection limit for tile loading.
- **Client**: React + Vite app with a custom **WebGPU** renderer. Tile scheduling, decode workers, and caching are implemented in TypeScript, mirroring the Rust scheduler's logic. WGSL shaders handle tile compositing.
- **HTTPS/HTTP3**: Server uses self-signed certs for local development. Generate certs in `web/server/certs/` (see Development Commands). Falls back to HTTP-only if certs are missing.
- **CORS**: Server allows both `http://` and `https://` origins for `localhost:5173` and `127.0.0.1:5173`. Add new origins in `web/server/main.py` if needed.
- **Pack v2 index format**: Magic `FPLIDX1\0`, version 1, 16-byte header, 12-byte entries (`u64 offset` + `u32 length`), `u16` cols/rows, row-major ordering. `length == 0` means missing tile.
