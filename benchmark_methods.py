"""Benchmark preprocessing runtime and output size.

This script is intentionally simple and uses the current preprocessing pipeline
(``VipsPyramidBuilder``). The older ``method=...`` benchmark was removed when the
builder API was simplified.
"""

import argparse
import csv
import time
from pathlib import Path

from fastpath.preprocess.pyramid import VipsPyramidBuilder

def get_dir_size_mb(path: Path) -> float:
    """Get total size of directory in MB."""
    total = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    return total / (1024 * 1024)


def benchmark(slides_dir: Path, output_base: Path, tile_size: int, runs: int) -> list[dict]:
    """Benchmark all slides with the current builder."""
    results = []
    output_base.mkdir(parents=True, exist_ok=True)
    slides = sorted(slides_dir.glob("*.svs"))

    for slide in slides:
        for run in range(1, runs + 1):
            label = f"tile{tile_size}"
            output_dir = output_base / label
            output_dir.mkdir(parents=True, exist_ok=True)

            print(f"\n=== {slide.name} | {label} | Run {run} ===")
            builder = VipsPyramidBuilder(tile_size=tile_size)

            start = time.perf_counter()
            result_path = builder.build(slide, output_dir, force=True)
            elapsed = time.perf_counter() - start

            size_mb = get_dir_size_mb(result_path) if result_path else 0

            results.append({
                "slide": slide.name,
                "label": label,
                "tile_size": tile_size,
                "run": run,
                "time_seconds": round(elapsed, 2),
                "output_size_mb": round(size_mb, 1),
            })
            print(f"    Time: {elapsed:.2f}s, Size: {size_mb:.1f} MB")

    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--slides-dir", default="WSI_examples")
    parser.add_argument("--output-base", default="benchmark_output")
    parser.add_argument("--tile-size", type=int, default=512)
    parser.add_argument("--runs", type=int, default=2)
    args = parser.parse_args()

    slides_dir = Path(args.slides_dir)
    output_base = Path(args.output_base)

    all_results = benchmark(slides_dir, output_base, args.tile_size, args.runs)

    # Write CSV
    csv_path = output_base / "benchmark_results.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=["slide", "label", "tile_size", "run", "time_seconds", "output_size_mb"]
        )
        writer.writeheader()
        writer.writerows(all_results)

    print(f"\n{'='*50}")
    print(f"Results saved to {csv_path}")


if __name__ == "__main__":
    main()
