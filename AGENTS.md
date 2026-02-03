# Repository Guidelines

## Project Structure & Module Organization
FastPATH is split into a viewer and a preprocessing CLI. Python sources live in `src/fastpath/`: `ui/` (PySide6 + QML), `ui/qml/` (QML components and `style/Theme.qml`), `preprocess/` (CLI pipeline, pyvips), `core/` (shared data like `core/types.py`), `ai/` (plugin system), and `config.py` (shared settings). The viewer and preprocessing modules must not import each other; they only share `core/types.py` and `preprocess/backends.py` and communicate via the filesystem (`.fastpath` output). The Rust tile scheduler is in `src/fastpath_core/` and is built via maturin. Tests are in `tests/`; sample slides live in `WSI_examples/`.

## Build, Test, and Development Commands
- `uv sync` — install Python deps.
- `uv run maturin develop --release --manifest-path src/fastpath_core/Cargo.toml` — build Rust extension required by the viewer (drop `--release` for faster iteration).
- `uv run python -m fastpath` or `run.bat` — launch the viewer.
- `uv run python -m fastpath.preprocess <slide.svs> -o <output_dir>` — build `.fastpath` pyramids.
- `uv run python -m pytest tests/` — run Python tests; `uv run python -m pytest tests/test_annotations.py -k "test_name"` for a subset.
- `cd src/fastpath_core && cargo test` — run Rust tests.

## Coding Style & Naming Conventions
Use 4-space indentation in Python and QML; follow existing layout and ordering in each module. Prefer type hints, `pathlib.Path`, and PySide6 (not PyQt). Naming: `snake_case` for functions/vars, `PascalCase` for classes, `test_*.py` for tests. QML styling lives in `src/fastpath/ui/qml/style/Theme.qml`; reuse it for colors and typography.

## Testing Guidelines
Pytest is the primary framework with `pytest-qt` for Qt tests. Use fixtures like `mock_fastpath_dir` for slide-related tests and the session-scoped `qapp` fixture for Qt widgets. Keep new tests near the module under test and mirror naming in `tests/`.

## Commit & Pull Request Guidelines
Git history favors a Conventional Commit style prefix such as `feat:`, `refactor:`, `docs:`, `test:`, `fix:` followed by a short imperative summary. PRs should include: a concise description, commands run, and screenshots for UI/QML changes. Call out any changes to `.fastpath` output format or configuration defaults.

## Configuration & Environment
Requires Python >=3.11, Rust toolchain, and system libvips with OpenSlide. On Windows, install to `C:/vips` or set `FASTPATH_VIPS_PATH`. Cache and performance settings are centralized in `src/fastpath/config.py`.

## Notes
- NuLite plugin dedup strategy: centroid-ownership (no Shapely dependency).
