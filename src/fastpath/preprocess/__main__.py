"""CLI entry point for FastPATH preprocessing."""

from __future__ import annotations

import logging
import os
import shutil
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import click
from tqdm import tqdm

from fastpath.config import (
    WSI_EXTENSIONS,
    VIPS_CONCURRENCY,
    VIPS_DISC_THRESHOLD,
    DEFAULT_PARALLEL_SLIDES,
)

logger = logging.getLogger(__name__)

from .pyramid import is_vips_dzsave_available
from .worker import process_single_slide


def is_wsi_file(path: Path) -> bool:
    """Check if a file is a supported WSI format."""
    return path.suffix.lower() in WSI_EXTENSIONS


def find_wsi_files(path: Path) -> list[Path]:
    """Find all WSI files in a path (file or directory)."""
    path = Path(path)
    if path.is_file():
        if is_wsi_file(path):
            return [path]
        return []
    elif path.is_dir():
        # Use set to avoid duplicates on case-insensitive filesystems (Windows)
        files = set()
        for ext in WSI_EXTENSIONS:
            files.update(path.glob(f"*{ext}"))
            files.update(path.glob(f"*{ext.upper()}"))
        return sorted(files)
    return []


@click.command()
@click.argument("input_path", type=click.Path(exists=True))
@click.option(
    "-o",
    "--output",
    type=click.Path(),
    default="./output",
    help="Output directory for .fastpath folders",
)
@click.option(
    "--tile-size",
    "-t",
    type=click.IntRange(64, 2048),
    default=512,
    help="Tile size in pixels (default: 512, range: 64-2048)",
)
@click.option(
    "--parallel-slides",
    "-p",
    type=int,
    default=DEFAULT_PARALLEL_SLIDES,
    help=f"Process multiple slides in parallel (default: {DEFAULT_PARALLEL_SLIDES})",
)
@click.option(
    "--force",
    "-f",
    is_flag=True,
    help="Force rebuild even if slide is already preprocessed",
)
def main(
    input_path: str,
    output: str,
    tile_size: int,
    parallel_slides: int,
    force: bool,
) -> None:
    """Preprocess whole-slide images into tile pyramids.

    INPUT_PATH can be a single WSI file or a directory containing WSI files.
    Supported formats: SVS, NDPI, TIF, TIFF, MRXS, VMS, VMU, SCN.

    Always produces 0.5 MPP (20x equivalent), JPEG Q80, using pyvips dzsave.

    Examples:

        # Process a single slide
        python -m fastpath.preprocess slide.svs -o ./output/

        # Process all slides in a directory
        python -m fastpath.preprocess ./slides/ -o ./output/

        # Process with larger tiles
        python -m fastpath.preprocess slide.svs -o ./output/ -t 1024
    """
    input_path = Path(input_path)
    output_dir = Path(output)

    # Find WSI files
    wsi_files = find_wsi_files(input_path)
    if not wsi_files:
        click.echo(f"No WSI files found in {input_path}", err=True)
        sys.exit(1)

    # Check pyvips availability
    if not is_vips_dzsave_available():
        click.echo(click.style(
            "Error: FastPATH requires pyvips with OpenSlide support. "
            "Please install libvips with OpenSlide enabled.",
            fg="red"
        ), err=True)
        sys.exit(1)

    click.echo(click.style("FastPATH Preprocessing", fg="cyan", bold=True))
    click.echo(click.style("=" * 40, fg="cyan"))
    click.echo(f"Found {len(wsi_files)} WSI file(s)")
    click.echo(f"Output directory: {output_dir}")
    click.echo(f"Tile size: {tile_size}px | Target: 0.5 MPP | JPEG Q80")
    if force:
        click.echo(click.style("Force mode: will rebuild existing pyramids", fg="yellow"))
    click.echo()

    output_dir.mkdir(parents=True, exist_ok=True)

    # Set VIPS tuning for processing
    os.environ["VIPS_CONCURRENCY"] = VIPS_CONCURRENCY
    os.environ["VIPS_DISC_THRESHOLD"] = VIPS_DISC_THRESHOLD

    success_count = 0
    skipped_count = 0
    error_count = 0
    errors = []

    # Always use parallel processing
    with ProcessPoolExecutor(max_workers=parallel_slides) as executor:
        futures = {
            executor.submit(
                process_single_slide,
                f,
                output_dir,
                tile_size,
                force,
            ): f
            for f in wsi_files
        }

        with tqdm(total=len(wsi_files), desc="Processing slides") as pbar:
            for future in as_completed(futures):
                slide_path = futures[future]
                try:
                    result, error, was_skipped = future.result()
                except Exception as e:
                    # Worker crashed - log error and clean up partial output
                    logger.error("Worker crashed processing %s: %s", slide_path, e)
                    error_count += 1
                    errors.append((slide_path, str(e)))
                    click.echo(f"\nWorker crashed processing {slide_path.name}: {e}", err=True)
                    # Clean up partial output if exists
                    partial_output = output_dir / (slide_path.stem + ".fastpath")
                    if partial_output.exists():
                        try:
                            shutil.rmtree(partial_output)
                            click.echo(f"  Cleaned up partial output: {partial_output}", err=True)
                        except OSError as cleanup_err:
                            click.echo(f"  Failed to clean up partial output: {cleanup_err}", err=True)
                    pbar.update(1)
                    continue

                if error:
                    error_count += 1
                    errors.append((slide_path, error))
                    click.echo(f"\nError processing {slide_path.name}: {error}", err=True)
                elif was_skipped:
                    skipped_count += 1
                else:
                    success_count += 1
                pbar.update(1)

    # Summary
    click.echo()
    click.echo(click.style("=" * 40, fg="cyan"))

    # Build summary message
    parts = []
    if success_count > 0:
        parts.append(click.style(f"{success_count} processed", fg="green"))
    if skipped_count > 0:
        parts.append(click.style(f"{skipped_count} skipped", fg="cyan"))
    if error_count > 0:
        parts.append(click.style(f"{error_count} failed", fg="red"))

    summary = ", ".join(parts) if parts else "Nothing to process"
    click.echo(click.style("Completed: ", bold=True) + summary)

    if skipped_count > 0 and not force:
        click.echo(click.style("  (use --force to rebuild skipped slides)", fg="cyan"))

    if errors:
        click.echo()
        click.echo(click.style("Failed slides:", fg="red"))
        for path, error in errors:
            click.echo(f"  {path.name}: {error}")
        sys.exit(1)


if __name__ == "__main__":
    main()
