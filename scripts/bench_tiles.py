"""Micro-benchmark for tile fetch + QImage conversion.

This is intended for quick local comparisons when changing tile transfer /
copying strategies. It does not attempt to emulate full QML behavior.

Examples:
  uv run python scripts/bench_tiles.py --fastpath-dir "example WSI.fastpath"
  FASTPATH_FORCE_QIMAGE_COPY=1 uv run python scripts/bench_tiles.py --iters 3
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import time
from pathlib import Path

from PySide6.QtGui import QImage

from fastpath_core import RustTileScheduler


def _percentile_ms(values_s: list[float], p: float) -> float:
    if not values_s:
        return 0.0
    xs = sorted(values_s)
    # Nearest-rank
    k = int(round((p / 100.0) * (len(xs) - 1)))
    k = max(0, min(k, len(xs) - 1))
    return xs[k] * 1000.0


def _truthy(v: str | None) -> bool:
    if v is None:
        return False
    return v.strip().lower() in {"1", "true", "yes"}


def _load_level_info(fastpath_dir: Path) -> list[dict]:
    meta = json.loads((fastpath_dir / "metadata.json").read_text(encoding="utf-8"))
    return list(meta["levels"])


def _pick_default_level(levels: list[dict]) -> int:
    # Highest resolution = smallest downsample
    return min(levels, key=lambda l: l["downsample"])["level"]


def _make_coords(
    level: int,
    cols: int,
    rows: int,
    start_col: int,
    start_row: int,
) -> list[tuple[int, int, int]]:
    out: list[tuple[int, int, int]] = []
    for r in range(start_row, start_row + rows):
        for c in range(start_col, start_col + cols):
            out.append((level, c, r))
    return out


def _run_pass(
    scheduler: RustTileScheduler,
    coords: list[tuple[int, int, int]],
    *,
    mode: str,
    tile_buffer: bool,
    qimage_copy: bool,
    iters: int,
) -> dict:
    fetch_s: list[float] = []
    qimage_s: list[float] = []
    total_tiles = 0

    fmt = QImage.Format.Format_RGB888

    for _ in range(iters):
        for level, col, row in coords:
            t0 = time.perf_counter()
            if mode == "rgb":
                tile = (
                    scheduler.get_tile_buffer(level, col, row)
                    if tile_buffer
                    else scheduler.get_tile(level, col, row)
                )
                t1 = time.perf_counter()
                if tile is None:
                    continue
                data, width, height = tile
                img = QImage(data, width, height, width * 3, fmt)
                if qimage_copy:
                    img = img.copy()
                _ = img  # keep local ref
                t2 = time.perf_counter()
            elif mode == "jpeg":
                jpeg = scheduler.get_tile_jpeg(level, col, row)
                t1 = time.perf_counter()
                if jpeg is None:
                    continue
                img = QImage.fromData(jpeg)
                _ = img
                t2 = time.perf_counter()
            else:
                raise ValueError(f"Unknown mode: {mode}")

            total_tiles += 1
            fetch_s.append(t1 - t0)
            qimage_s.append(t2 - t1)

    stats = scheduler.cache_stats()
    return {
        "tiles": total_tiles,
        "fetch_ms_p50": _percentile_ms(fetch_s, 50),
        "fetch_ms_p95": _percentile_ms(fetch_s, 95),
        "qimage_ms_p50": _percentile_ms(qimage_s, 50),
        "qimage_ms_p95": _percentile_ms(qimage_s, 95),
        "fetch_ms_mean": (statistics.mean(fetch_s) * 1000.0) if fetch_s else 0.0,
        "qimage_ms_mean": (statistics.mean(qimage_s) * 1000.0) if qimage_s else 0.0,
        "cache_stats": stats,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--fastpath-dir",
        type=Path,
        default=Path("example WSI.fastpath"),
        help="Path to a .fastpath directory (default: example WSI.fastpath)",
    )
    parser.add_argument("--level", type=int, default=None)
    parser.add_argument("--cols", type=int, default=8)
    parser.add_argument("--rows", type=int, default=4)
    parser.add_argument("--start-col", type=int, default=0)
    parser.add_argument("--start-row", type=int, default=0)
    parser.add_argument("--iters", type=int, default=5)
    parser.add_argument("--mode", choices=["rgb", "jpeg"], default="rgb")
    parser.add_argument(
        "--tile-buffer",
        action="store_true",
        help="Use Rust get_tile_buffer() (zero-copy) in rgb mode",
    )
    parser.add_argument(
        "--qimage-copy",
        action="store_true",
        help="Force an extra QImage.copy() per tile (mimics old behavior)",
    )
    parser.add_argument(
        "--cache-mb",
        type=int,
        default=4096,
        help="Rust L1 cache size in MB (default 4096; keep fixed for comparisons)",
    )
    parser.add_argument(
        "--l2-cache-mb",
        type=int,
        default=32768,
        help="Rust L2 cache size in MB (default 32768; keep fixed for comparisons)",
    )
    parser.add_argument("--prefetch-distance", type=int, default=0)
    args = parser.parse_args()

    fastpath_dir: Path = args.fastpath_dir
    if not fastpath_dir.exists():
        raise SystemExit(f"Not found: {fastpath_dir}")

    levels = _load_level_info(fastpath_dir)
    level = args.level if args.level is not None else _pick_default_level(levels)

    coords = _make_coords(level, args.cols, args.rows, args.start_col, args.start_row)
    print(
        f"Slide={fastpath_dir} mode={args.mode} level={level} tiles={len(coords)} iters={args.iters} "
        f"tile_buffer={args.tile_buffer} qimage_copy={args.qimage_copy}"
    )

    # Pass A: cold (new scheduler)
    scheduler = RustTileScheduler(
        cache_size_mb=args.cache_mb,
        l2_cache_size_mb=args.l2_cache_mb,
        prefetch_distance=args.prefetch_distance,
    )
    scheduler.load(str(fastpath_dir))
    scheduler.reset_cache_stats()
    a = _run_pass(
        scheduler,
        coords,
        mode=args.mode,
        tile_buffer=args.tile_buffer,
        qimage_copy=args.qimage_copy,
        iters=args.iters,
    )

    # Pass B: warm L1
    scheduler.reset_cache_stats()
    b = _run_pass(
        scheduler,
        coords,
        mode=args.mode,
        tile_buffer=args.tile_buffer,
        qimage_copy=args.qimage_copy,
        iters=args.iters,
    )

    # Pass C: warm L2, cold-ish L1 (close/load clears L1 only)
    scheduler.close()
    scheduler.load(str(fastpath_dir))
    scheduler.reset_cache_stats()
    c = _run_pass(
        scheduler,
        coords,
        mode=args.mode,
        tile_buffer=args.tile_buffer,
        qimage_copy=args.qimage_copy,
        iters=args.iters,
    )

    def fmt_pass(label: str, r: dict) -> None:
        s = r["cache_stats"]
        print(
            f"{label}: tiles={r['tiles']} fetch(ms) p50={r['fetch_ms_p50']:.3f} "
            f"p95={r['fetch_ms_p95']:.3f} mean={r['fetch_ms_mean']:.3f} | "
            f"qimage(ms) p50={r['qimage_ms_p50']:.3f} p95={r['qimage_ms_p95']:.3f} "
            f"mean={r['qimage_ms_mean']:.3f} | "
            f"L1 hits={s.get('hits', 0)} misses={s.get('misses', 0)} tiles={s.get('num_tiles', 0)} | "
            f"L2 hits={s.get('l2_hits', 0)} misses={s.get('l2_misses', 0)} tiles={s.get('l2_num_tiles', 0)}"
        )

    fmt_pass("cold", a)
    fmt_pass("warm L1", b)
    fmt_pass("warm L2", c)

    force_copy_env = _truthy(os.environ.get("FASTPATH_FORCE_QIMAGE_COPY"))
    if force_copy_env and not args.qimage_copy:
        print(
            "Note: FASTPATH_FORCE_QIMAGE_COPY=1 is set but --qimage-copy was not passed; "
            "this script's --qimage-copy controls only the local QImage path."
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
