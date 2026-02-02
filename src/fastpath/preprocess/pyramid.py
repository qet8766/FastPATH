"""Pyramid generation for whole-slide images."""

from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from fastpath.config import (
    JPEG_QUALITY,
    TARGET_MPP,
    THUMBNAIL_JPEG_QUALITY,
    THUMBNAIL_MAX_SIZE,
)
from fastpath.core.types import LevelInfo

from .metadata import PyramidMetadata, PyramidStatus, check_pyramid_status

logger = logging.getLogger(__name__)

# Import backends first to set up DLL paths on Windows
from .backends import is_vips_available

# Check for pyvips openslideload support (imports pyvips after backends has set up DLL paths)

_HAS_VIPS_OPENSLIDE = False
pyvips: Any = None
try:
    import pyvips
    # Check if openslideload is available (requires libvips with OpenSlide support)
    try:
        pyvips.Operation.generate_docstring('openslideload')
        _HAS_VIPS_OPENSLIDE = True
    except pyvips.error.Error:
        _HAS_VIPS_OPENSLIDE = False
except (ImportError, OSError):
    pass  # pyvips remains None


def is_vips_dzsave_available() -> bool:
    """Check if pyvips with OpenSlide support is available for dzsave().

    This enables the fast preprocessing mode using libvips' native
    Deep Zoom tile generation.

    Returns:
        True if pyvips.Image.openslideload is available
    """
    return _HAS_VIPS_OPENSLIDE


class VipsPyramidBuilder:
    """Fast pyramid builder using pyvips dzsave().

    Loads OpenSlide level 0 and resizes to exactly 0.5 MPP (20x equivalent),
    then generates tile pyramid using libvips' native Deep Zoom generator.
    Always outputs JPEG Q80.

    Requirements:
        - pyvips with OpenSlide support (libvips compiled with openslide)

    Output format:
        - tiles_files/N/col_row.jpg (Deep Zoom structure)
        - Level 0 = lowest resolution, level N = highest resolution (native dzsave convention)
    """

    def __init__(self, tile_size: int = 512) -> None:
        if not _HAS_VIPS_OPENSLIDE:
            raise RuntimeError(
                "VipsPyramidBuilder requires pyvips with OpenSlide support. "
                "Install libvips with OpenSlide enabled."
            )
        self.tile_size = tile_size

    def build(
        self,
        slide_path: Path,
        output_dir: Path,
        progress_callback: Callable[[str, int, int], None] | None = None,
        force: bool = False,
    ) -> Path | None:
        """Build a tile pyramid using pyvips dzsave().

        Args:
            slide_path: Path to the source WSI file
            output_dir: Directory to create the .fastpath folder in
            progress_callback: Optional callback(stage, current, total)
            force: If True, rebuild even if complete pyramid exists

        Returns:
            Path to the created .fastpath directory, or None if skipped
        """
        slide_path = Path(slide_path)
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Create output directory
        pyramid_name = slide_path.stem + ".fastpath"
        pyramid_dir = output_dir / pyramid_name

        # Check existing pyramid status
        status = check_pyramid_status(pyramid_dir)

        if status == PyramidStatus.COMPLETE and not force:
            logger.info("Skipping %s: already preprocessed (use --force to rebuild)", slide_path.name)
            return None

        if status in (PyramidStatus.INCOMPLETE, PyramidStatus.CORRUPTED, PyramidStatus.COMPLETE):
            if status == PyramidStatus.INCOMPLETE:
                logger.info("Found incomplete preprocessing for %s, cleaning up...", slide_path.name)
            elif status == PyramidStatus.CORRUPTED:
                logger.warning("Found corrupted preprocessing for %s, cleaning up...", slide_path.name)
            elif force:
                logger.info("Force rebuild for %s, removing existing...", slide_path.name)
            shutil.rmtree(pyramid_dir)

        pyramid_dir.mkdir()

        # Create subdirectories
        annotations_dir = pyramid_dir / "annotations"
        annotations_dir.mkdir()

        # Load level 0 (highest resolution) and resize to 0.5 MPP
        logger.info("Loading slide level 0 with pyvips...")
        image = pyvips.Image.openslideload(str(slide_path), level=0)
        base_mpp = self._get_base_mpp(slide_path)
        logger.info("Loaded %s: %d x %d px (MPP %.4f)", slide_path.name, image.width, image.height, base_mpp)

        if base_mpp < TARGET_MPP:
            resize_factor = base_mpp / TARGET_MPP
            logger.info("Resizing by %.3f for %.1f MPP...", resize_factor, TARGET_MPP)
            image = image.resize(resize_factor, vscale=resize_factor, kernel="lanczos3")
            actual_mpp = TARGET_MPP
            logger.info("Resized to %d x %d px", image.width, image.height)
        elif base_mpp > TARGET_MPP:
            logger.warning(
                "Source MPP %.3f is coarser than target %.1f — using source resolution as-is",
                base_mpp, TARGET_MPP,
            )
            actual_mpp = base_mpp
        else:
            actual_mpp = base_mpp

        actual_mag = 10.0 / actual_mpp if actual_mpp > 0 else 10.0

        dimensions = (image.width, image.height)

        # Generate thumbnail
        if progress_callback:
            progress_callback("thumbnail", 0, 1)
        logger.info("Generating thumbnail...")
        thumb = image.thumbnail_image(THUMBNAIL_MAX_SIZE)
        thumb.jpegsave(str(pyramid_dir / "thumbnail.jpg"), Q=THUMBNAIL_JPEG_QUALITY)
        logger.debug("Thumbnail generated")

        # Generate tile pyramid using dzsave - THE FAST PART
        if progress_callback:
            progress_callback("dzsave", 0, 1)
        logger.info("Generating tile pyramid with dzsave...")

        # dzsave with layout="dz" creates: pyramid_dir/tiles_files/N/col_row.jpeg
        image.dzsave(
            str(pyramid_dir / "tiles"),
            tile_size=self.tile_size,
            overlap=0,
            suffix=f".jpg[Q={JPEG_QUALITY},interlace]",  # Progressive JPEG Q80
            depth="onetile",  # Stop when tile fits in one tile
            layout="dz",  # Deep Zoom layout: tiles_files/level/col_row.jpg
            strip=True,  # Remove metadata for smaller/faster tiles
        )
        logger.debug("Tile pyramid generated")

        # Read dzsave output to calculate level info
        levels = self._calculate_levels_from_dzsave(pyramid_dir / "tiles_files")

        # Write metadata
        metadata = PyramidMetadata(
            version="1.0",
            source_file=slide_path.name,
            source_mpp=base_mpp,
            target_mpp=actual_mpp,
            target_magnification=actual_mag,
            tile_size=self.tile_size,
            dimensions=dimensions,
            levels=levels,
            background_color=(255, 255, 255),  # White background default
            preprocessed_at=datetime.now(timezone.utc).isoformat(),
        )

        with open(pyramid_dir / "metadata.json", "w") as f:
            json.dump(metadata.to_dict(), f, indent=2)

        # Create empty default annotation file
        with open(annotations_dir / "default.geojson", "w") as f:
            json.dump(
                {"type": "FeatureCollection", "features": []}, f, indent=2
            )

        logger.info("Generated %d pyramid levels for %s", len(levels), slide_path.name)
        return pyramid_dir

    def _get_base_mpp(self, slide_path: Path) -> float:
        """Get microns-per-pixel at level 0 from slide metadata.

        Returns:
            Base MPP value, or 0.25 as fallback (assumes 40x).
        """
        try:
            image = pyvips.Image.openslideload(str(slide_path), level=0)

            for field in ("openslide.mpp-x", "aperio.MPP"):
                try:
                    value = image.get(field)
                    if value:
                        return float(value)
                except (ValueError, TypeError, KeyError, pyvips.error.Error):
                    continue

            # No MPP metadata — assume 40x (0.25 MPP)
            logger.warning("No MPP metadata in %s, assuming 40x (0.25 MPP)", slide_path.name)
            return 0.25

        except (OSError, pyvips.error.Error):
            logger.warning("Cannot read MPP from %s, assuming 40x (0.25 MPP)", slide_path.name)
            return 0.25

    def _calculate_levels_from_dzsave(self, dzsave_dir: Path) -> list[LevelInfo]:
        """Calculate level info from dzsave output.

        dzsave creates levels from 0 (smallest/lowest resolution) to N
        (largest/full resolution). Level numbers are used directly — no
        inversion needed.

        Args:
            dzsave_dir: Path to slide_files directory created by dzsave

        Returns:
            List of LevelInfo in native dzsave order (0 = lowest resolution)
        """
        if not dzsave_dir.exists():
            return []

        # Find all level directories
        level_dirs = sorted(
            [d for d in dzsave_dir.iterdir() if d.is_dir() and d.name.isdigit()],
            key=lambda d: int(d.name)
        )

        if not level_dirs:
            return []

        max_dz_level = int(level_dirs[-1].name)

        levels = []
        for level_dir in level_dirs:
            dz_level = int(level_dir.name)

            # Count tiles to determine grid size
            tiles = list(level_dir.glob("*.jpg"))
            if not tiles:
                continue

            # Parse tile coordinates to find max col/row
            max_col = 0
            max_row = 0
            for tile_path in tiles:
                parts = tile_path.stem.split("_")
                if len(parts) == 2:
                    col, row = int(parts[0]), int(parts[1])
                    max_col = max(max_col, col)
                    max_row = max(max_row, row)

            cols = max_col + 1
            rows = max_row + 1
            downsample = 2 ** (max_dz_level - dz_level)

            levels.append(LevelInfo(
                level=dz_level,
                downsample=downsample,
                cols=cols,
                rows=rows,
            ))

        return levels


def build_pyramid(
    slide_path: Path,
    output_dir: Path,
    tile_size: int = 512,
    progress_callback: Callable[[str, int, int], None] | None = None,
    force: bool = False,
) -> Path | None:
    """Build a tile pyramid using VipsPyramidBuilder.

    Always produces 0.5 MPP, JPEG Q80.

    Args:
        slide_path: Path to WSI file
        output_dir: Output directory
        tile_size: Tile size in pixels
        progress_callback: Progress callback function
        force: Force rebuild even if already complete

    Returns:
        Path to the created .fastpath directory, or None if skipped

    Raises:
        RuntimeError: If pyvips with OpenSlide support is not available
    """
    builder = VipsPyramidBuilder(tile_size=tile_size)
    return builder.build(slide_path, output_dir, progress_callback, force=force)
