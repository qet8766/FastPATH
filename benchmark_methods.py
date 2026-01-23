"""Benchmark: Level 1 (direct) vs Level 0 (resized to MPP 0.5)."""

import csv
import time
from pathlib import Path

from fastpath.preprocess.pyramid import VipsPyramidBuilder

SLIDES_DIR = Path("example_wsi")
OUTPUT_BASE = Path("benchmark_output")
RUNS = 2


def get_dir_size_mb(path: Path) -> float:
    """Get total size of directory in MB."""
    total = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    return total / (1024 * 1024)


def benchmark_method(method: str, label: str) -> list[dict]:
    """Benchmark all slides with given method."""
    results = []
    output_dir = OUTPUT_BASE / label
    output_dir.mkdir(parents=True, exist_ok=True)

    slides = list(SLIDES_DIR.glob("*.svs"))

    for slide in slides:
        for run in range(1, RUNS + 1):
            print(f"\n=== {slide.name} | {label} | Run {run} ===")

            builder = VipsPyramidBuilder(method=method)

            start = time.perf_counter()
            result_path = builder.build(slide, output_dir, force=True)
            elapsed = time.perf_counter() - start

            size_mb = get_dir_size_mb(result_path) if result_path else 0

            results.append({
                "slide": slide.name,
                "method": label,
                "run": run,
                "time_seconds": round(elapsed, 2),
                "output_size_mb": round(size_mb, 1),
            })
            print(f"    Time: {elapsed:.2f}s, Size: {size_mb:.1f} MB")

    return results


def main():
    all_results = []

    # Method A: Current approach (level 1, ~MPP 1.0)
    all_results.extend(benchmark_method("level1", "level1_mpp1.0"))

    # Method B: New approach (level 0 resized to MPP 0.5)
    all_results.extend(benchmark_method("level0_resized", "level0_mpp0.5"))

    # Write CSV
    csv_path = OUTPUT_BASE / "benchmark_results.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=["slide", "method", "run", "time_seconds", "output_size_mb"]
        )
        writer.writeheader()
        writer.writerows(all_results)

    print(f"\n{'='*50}")
    print(f"Results saved to {csv_path}")


if __name__ == "__main__":
    main()
