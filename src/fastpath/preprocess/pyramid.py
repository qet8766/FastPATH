"""Pyramid generation for whole-slide images."""

from __future__ import annotations

import json
import logging
import shutil
import struct
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from fastpath.config import (
    BACKGROUND_COLOR,
    JPEG_QUALITY,
    TARGET_MPP,
    THUMBNAIL_JPEG_QUALITY,
    THUMBNAIL_MAX_SIZE,
)
from fastpath.core.types import LevelInfo

from .metadata import PyramidMetadata, PyramidStatus, check_pyramid_status, pyramid_dir_for_slide

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


def require_vips_openslide() -> None:
    """Raise RuntimeError if pyvips with OpenSlide support is not available.

    Raises:
        RuntimeError: If pyvips or OpenSlide support is missing
    """
    if not _HAS_VIPS_OPENSLIDE:
        raise RuntimeError(
            "VipsPyramidBuilder requires pyvips with OpenSlide support. "
            "Install libvips with OpenSlide enabled."
        )


class VipsPyramidBuilder:
    """Fast pyramid builder using pyvips dzsave().

    Loads OpenSlide level 0 and resizes to exactly 0.5 MPP (20x equivalent),
    then generates tile pyramid using libvips' native Deep Zoom generator.
    Always outputs JPEG Q80.

    Requirements:
        - pyvips with OpenSlide support (libvips compiled with openslide)

    Output format:
        - tiles.pack + tiles.idx (packed tile store)
        - Level 0 = lowest resolution, level N = highest resolution (native dzsave convention)
    """

    def __init__(self, tile_size: int = 512) -> None:
        require_vips_openslide()
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

        pyramid_dir = self._resolve_pyramid_dir(slide_path, output_dir)
        if self._handle_existing_pyramid(pyramid_dir, slide_path.name, force):
            return None
        self._prepare_pyramid_dir(pyramid_dir)

        self._generate_thumbnail(slide_path, pyramid_dir, progress_callback)

        image, base_mpp, actual_mpp, actual_mag, dimensions = self._load_and_resize(
            slide_path, progress_callback
        )
        self._run_dzsave(image, pyramid_dir, progress_callback)
        levels = self._calculate_levels_from_dimensions(dimensions[0], dimensions[1], self.tile_size)
        self._pack_tiles(pyramid_dir, levels)
        self._write_metadata(
            pyramid_dir, slide_path, base_mpp, actual_mpp, actual_mag, dimensions, levels
        )

        logger.info("Generated %d pyramid levels for %s", len(levels), slide_path.name)
        return pyramid_dir

    def _resolve_pyramid_dir(self, slide_path: Path, output_dir: Path) -> Path:
        """Construct the .fastpath output path and ensure output_dir exists.

        Args:
            slide_path: Path to the source WSI file
            output_dir: Parent directory for the .fastpath folder

        Returns:
            Path to the .fastpath directory (may not exist yet)
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        return pyramid_dir_for_slide(slide_path, output_dir)

    def _handle_existing_pyramid(
        self, pyramid_dir: Path, slide_name: str, force: bool
    ) -> bool:
        """Check existing pyramid status and clean up if needed.

        Args:
            pyramid_dir: Path to the .fastpath directory
            slide_name: Name of the source slide (for logging)
            force: If True, rebuild even if complete

        Returns:
            True if the build should be skipped (already complete and not forced)
        """
        status = check_pyramid_status(pyramid_dir)

        if status == PyramidStatus.COMPLETE and not force:
            logger.info("Skipping %s: already preprocessed (use --force to rebuild)", slide_name)
            return True

        if status in (PyramidStatus.INCOMPLETE, PyramidStatus.CORRUPTED, PyramidStatus.COMPLETE):
            if status == PyramidStatus.INCOMPLETE:
                logger.info("Found incomplete preprocessing for %s, cleaning up...", slide_name)
            elif status == PyramidStatus.CORRUPTED:
                logger.warning("Found corrupted preprocessing for %s, cleaning up...", slide_name)
            elif force:
                logger.info("Force rebuild for %s, removing existing...", slide_name)
            shutil.rmtree(pyramid_dir)

        return False

    def _prepare_pyramid_dir(self, pyramid_dir: Path) -> None:
        """Create the pyramid directory and its subdirectories.

        Args:
            pyramid_dir: Path to the .fastpath directory to create
        """
        pyramid_dir.mkdir()
        (pyramid_dir / "annotations").mkdir()

    def _load_and_resize(
        self,
        slide_path: Path,
        progress_callback: Callable[[str, int, int], None] | None = None,
    ) -> tuple[Any, float, float, float, tuple[int, int]]:
        """Load slide at level 0 and resize to TARGET_MPP.

        Args:
            slide_path: Path to the source WSI file
            progress_callback: Optional callback(stage, current, total)

        Returns:
            Tuple of (image, base_mpp, actual_mpp, actual_magnification, dimensions)
        """
        if progress_callback:
            progress_callback("load", 0, 1)
        logger.info("Loading slide level 0 with pyvips...")
        image = pyvips.Image.openslideload(str(slide_path), level=0)
        base_mpp = self._get_base_mpp(image, slide_path.name)
        logger.info("Loaded %s: %d x %d px (MPP %.4f)", slide_path.name, image.width, image.height, base_mpp)

        if base_mpp < TARGET_MPP:
            if progress_callback:
                progress_callback("resize", 0, 1)
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

        return image, base_mpp, actual_mpp, actual_mag, dimensions

    def _generate_thumbnail(
        self,
        slide_path: Path,
        pyramid_dir: Path,
        progress_callback: Callable[[str, int, int], None] | None,
    ) -> None:
        """Generate and save the slide thumbnail.

        Tries to extract an embedded thumbnail/macro image from the WSI
        (instant, no pixel processing). Falls back to shrink-on-load from
        the file, which reads at an appropriate lower resolution level.

        Args:
            slide_path: Path to the source WSI file
            pyramid_dir: Path to the .fastpath directory
            progress_callback: Optional progress callback
        """
        if progress_callback:
            progress_callback("thumbnail", 0, 1)
        logger.info("Generating thumbnail...")

        thumb = None
        # Try extracting embedded thumbnail/macro from the WSI (no pipeline eval)
        for associated in ("thumbnail", "macro"):
            try:
                thumb = pyvips.Image.openslideload(str(slide_path), associated=associated)
                if max(thumb.width, thumb.height) > THUMBNAIL_MAX_SIZE:
                    thumb = thumb.thumbnail_image(THUMBNAIL_MAX_SIZE)
                break
            except pyvips.error.Error:
                continue

        # Fallback: shrink-on-load from file (reads at appropriate resolution level)
        if thumb is None:
            thumb = pyvips.Image.thumbnail(str(slide_path), THUMBNAIL_MAX_SIZE)

        # Flatten alpha channel (some associated images have 4 bands)
        if thumb.bands == 4:
            thumb = thumb.flatten()

        thumb.jpegsave(str(pyramid_dir / "thumbnail.jpg"), Q=THUMBNAIL_JPEG_QUALITY)
        logger.debug("Thumbnail generated")

    def _run_dzsave(
        self,
        image: Any,
        pyramid_dir: Path,
        progress_callback: Callable[[str, int, int], None] | None,
    ) -> None:
        """Run dzsave to generate the tile pyramid.

        Args:
            image: pyvips.Image of the slide
            pyramid_dir: Path to the .fastpath directory
            progress_callback: Optional progress callback
        """
        if progress_callback:
            progress_callback("dzsave", 0, 1)
        logger.info("Generating tile pyramid with dzsave...")

        # Enable vips progress signals for smooth per-tile updates
        if progress_callback:
            last_percent = -1
            cancelled = False

            def _on_eval(_image: Any, progress: Any) -> None:
                nonlocal last_percent, cancelled
                if cancelled:
                    return
                percent = progress.percent
                if percent != last_percent:
                    last_percent = percent
                    try:
                        progress_callback("dzsave_progress", percent, 100)
                    except InterruptedError:
                        cancelled = True
                        raise

            image.set_progress(True)
            image.signal_connect("eval", _on_eval)

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

    def _pack_tiles(self, pyramid_dir: Path, levels: list[LevelInfo]) -> None:
        """Pack dzsave tiles into tiles.pack/tiles.idx and remove the dzsave output."""
        tiles_dir = pyramid_dir / "tiles_files"
        if not tiles_dir.exists():
            raise RuntimeError(f"Missing dzsave tiles at {tiles_dir}")

        pack_path = pyramid_dir / "tiles.pack"
        idx_path = pyramid_dir / "tiles.idx"

        header_struct = struct.Struct("<8sII")
        level_struct = struct.Struct("<IIIQ")
        entry_struct = struct.Struct("<QII")
        magic = b"FPTIDX1\0"
        version = 1

        with open(pack_path, "wb") as pack_file, open(idx_path, "wb") as idx_file:
            idx_file.write(header_struct.pack(magic, version, len(levels)))

            entry_offset = 0
            for info in levels:
                idx_file.write(
                    level_struct.pack(
                        info.level, info.cols, info.rows, entry_offset
                    )
                )
                entry_offset += info.cols * info.rows * entry_struct.size

            pack_offset = 0
            for info in levels:
                level_dir = tiles_dir / str(info.level)
                if not level_dir.exists():
                    raise RuntimeError(f"Missing level directory: {level_dir}")
                for row in range(info.rows):
                    for col in range(info.cols):
                        tile_path = level_dir / f"{col}_{row}.jpg"
                        data = None
                        if tile_path.exists():
                            data = tile_path.read_bytes()
                        else:
                            alt_path = level_dir / f"{col}_{row}.jpeg"
                            if alt_path.exists():
                                data = alt_path.read_bytes()

                        if data is None:
                            idx_file.write(entry_struct.pack(0, 0, 0))
                            continue

                        pack_file.write(data)
                        idx_file.write(entry_struct.pack(pack_offset, len(data), 0))
                        pack_offset += len(data)

        shutil.rmtree(tiles_dir)
        dzi_path = pyramid_dir / "tiles.dzi"
        if dzi_path.exists():
            dzi_path.unlink()

    def _write_metadata(
        self,
        pyramid_dir: Path,
        slide_path: Path,
        base_mpp: float,
        actual_mpp: float,
        actual_mag: float,
        dimensions: tuple[int, int],
        levels: list[LevelInfo],
    ) -> None:
        """Write metadata.json and default.geojson to the pyramid directory.

        Args:
            pyramid_dir: Path to the .fastpath directory
            slide_path: Path to the source WSI file
            base_mpp: Original microns-per-pixel
            actual_mpp: Actual MPP after resize
            actual_mag: Actual magnification after resize
            dimensions: (width, height) of the resized image
            levels: List of LevelInfo from dzsave output
        """
        metadata = PyramidMetadata(
            version="1.0",
            source_file=slide_path.name,
            source_mpp=base_mpp,
            target_mpp=actual_mpp,
            target_magnification=actual_mag,
            tile_size=self.tile_size,
            dimensions=dimensions,
            levels=levels,
            background_color=BACKGROUND_COLOR,
            preprocessed_at=datetime.now(timezone.utc).isoformat(),
            tile_format="pack_v1",
        )

        with open(pyramid_dir / "metadata.json", "w") as f:
            json.dump(metadata.to_dict(), f, indent=2)

        # Create empty default annotation file
        annotations_dir = pyramid_dir / "annotations"
        with open(annotations_dir / "default.geojson", "w") as f:
            json.dump(
                {"type": "FeatureCollection", "features": []}, f, indent=2
            )

    def _get_base_mpp(self, image: Any, slide_name: str) -> float:
        """Get microns-per-pixel at level 0 from already-loaded image metadata.

        Args:
            image: pyvips.Image already opened with openslideload
            slide_name: Slide filename for log messages

        Returns:
            Base MPP value, or 0.25 as fallback (assumes 40x).
        """
        for field in ("openslide.mpp-x", "aperio.MPP"):
            try:
                value = image.get(field)
                if value and float(value) > 0:
                    return float(value)
            except (ValueError, TypeError, KeyError, pyvips.error.Error):
                continue

        # No MPP metadata — assume 40x (0.25 MPP)
        logger.warning("No MPP metadata in %s, assuming 40x (0.25 MPP)", slide_name)
        return 0.25

    def _calculate_levels_from_dimensions(
        self, width: int, height: int, tile_size: int
    ) -> list[LevelInfo]:
        """Calculate level info from image dimensions and tile size.

        Computes the pyramid structure mathematically instead of scanning
        the filesystem. Uses iterative ceiling-halving to match libvips
        dzsave with ``depth="onetile"``.

        Args:
            width: Image width in pixels
            height: Image height in pixels
            tile_size: Tile size in pixels

        Returns:
            List of LevelInfo in dzsave order (0 = lowest resolution)
        """
        dims = [(width, height)]
        w, h = width, height
        while w > tile_size or h > tile_size:
            w = (w + 1) // 2
            h = (h + 1) // 2
            dims.append((w, h))

        dims.reverse()  # level 0 = smallest
        max_level = len(dims) - 1

        levels = []
        for i, (lw, lh) in enumerate(dims):
            levels.append(LevelInfo(
                level=i,
                downsample=2 ** (max_level - i),
                cols=(lw + tile_size - 1) // tile_size,
                rows=(lh + tile_size - 1) // tile_size,
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
