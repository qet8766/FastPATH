"""Worker function for parallel preprocessing.

This module exists separately from __main__.py to support Windows multiprocessing,
which requires worker functions to be importable (not defined in __main__).
"""

from __future__ import annotations

from pathlib import Path

from .pyramid import VipsPyramidBuilder


def process_single_slide(
    slide_path: Path,
    output_dir: Path,
    tile_size: int,
    quality: int,
    force: bool = False,
    target_mpp: float | None = None,
) -> tuple[Path | None, str | None, bool]:
    """Process a single slide.

    Args:
        slide_path: Path to the WSI file
        output_dir: Output directory
        tile_size: Tile size in pixels
        quality: JPEG quality
        force: Force rebuild
        target_mpp: Override MPP value (used when slide metadata unavailable)

    Returns:
        Tuple of (result_path, error_message, was_skipped)
        - result_path: Path to .fastpath dir, or None if skipped/error
        - error_message: Error string if failed, None otherwise
        - was_skipped: True if slide was skipped (already complete)
    """
    try:
        builder = VipsPyramidBuilder(
            tile_size=tile_size,
            jpeg_quality=quality,
            target_mpp_override=target_mpp,
        )
        result = builder.build(slide_path, output_dir, force=force)
        if result is None:
            # Slide was skipped (already complete)
            return None, None, True
        return result, None, False
    except Exception as e:
        return None, str(e), False
