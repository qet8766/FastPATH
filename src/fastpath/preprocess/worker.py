"""Worker function for parallel preprocessing.

This module exists separately from __main__.py to support Windows multiprocessing,
which requires worker functions to be importable (not defined in __main__).
"""

from __future__ import annotations

import logging
from pathlib import Path

from .pyramid import VipsPyramidBuilder

logger = logging.getLogger(__name__)


def process_single_slide(
    slide_path: Path,
    output_dir: Path,
    tile_size: int,
    force: bool = False,
) -> tuple[Path | None, str | None, bool]:
    """Process a single slide.

    Always produces 0.5 MPP, JPEG Q80.

    Args:
        slide_path: Path to the WSI file
        output_dir: Output directory
        tile_size: Tile size in pixels
        force: Force rebuild

    Returns:
        Tuple of (result_path, error_message, was_skipped)
        - result_path: Path to .fastpath dir, or None if skipped/error
        - error_message: Error string if failed, None otherwise
        - was_skipped: True if slide was skipped (already complete)
    """
    logger.info("Processing %s", slide_path.name)
    try:
        builder = VipsPyramidBuilder(tile_size=tile_size)
        result = builder.build(slide_path, output_dir, force=force)
        if result is None:
            # Slide was skipped (already complete)
            return None, None, True
        return result, None, False
    except Exception as e:
        logger.error("Failed to process %s: %s", slide_path.name, e)
        return None, str(e), False
