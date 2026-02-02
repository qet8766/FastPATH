# FastPATH

Extensible pathology whole-slide image (WSI) viewer with a preprocessing-first architecture. Hybrid Python + QML + Rust.

## Requirements

- Python >= 3.11
- Rust toolchain (for building the native tile scheduler)
- [System libvips](https://github.com/libvips/build-win64-mxe/releases) with OpenSlide support (the "all" variant, **not** `pyvips-binary`)

On Windows, extract libvips to `C:/vips` (or set `FASTPATH_VIPS_PATH`).

## Installation

```bash
uv sync
uv run maturin develop --release --manifest-path src/fastpath_core/Cargo.toml
```

The Rust build uses LTO and `codegen-units = 1`, so the first build is slow. Drop `--release` for faster iteration.

## Usage

### Viewer

```bash
uv run python -m fastpath
```

### Preprocessing CLI

Converts WSI files into tile pyramids (0.5 MPP / 20x equivalent, JPEG Q80) for the viewer.

```bash
# Single slide
uv run python -m fastpath.preprocess slide.svs -o ./output/

# All slides in a directory
uv run python -m fastpath.preprocess ./slides/ -o ./output/
```

Supported formats: SVS, NDPI, TIF, TIFF, MRXS, VMS, VMU, SCN.

Options: `--tile-size/-t` (64-2048, default 512), `--parallel-slides/-p` (default 3), `--force/-f` (rebuild existing).

## Architecture

The codebase has two independent workloads:

- **Viewer** (`ui/`, `core/`, `ai/`, `fastpath_core/`) -- PySide6/QML frontend with a Rust tile scheduler for high-performance caching and SIMD JPEG decoding.
- **Preprocessing CLI** (`preprocess/`) -- Standalone batch processor using pyvips `dzsave`.

They share only data classes (`core/types.py`) and a pyvips wrapper (`preprocess/backends.py`), communicating through the filesystem: preprocessing writes `.fastpath` directories, the viewer reads them.

## Tests

```bash
uv run python -m pytest tests/                                   # All tests
uv run python -m pytest tests/test_annotations.py -k "test_name" # Single test
cd src/fastpath_core && cargo test                                # Rust tests
```

## License

MIT
