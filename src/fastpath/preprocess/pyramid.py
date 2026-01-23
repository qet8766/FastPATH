"""Pyramid generation for whole-slide images."""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from fastpath.core.types import LevelInfo

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


class PyramidStatus(Enum):
    """Status of an existing pyramid directory."""

    NOT_EXISTS = "not_exists"  # No .fastpath directory
    COMPLETE = "complete"  # Valid and complete
    INCOMPLETE = "incomplete"  # Missing required files
    CORRUPTED = "corrupted"  # Invalid metadata or structure


def check_pyramid_status(pyramid_dir: Path) -> PyramidStatus:
    """Check the status of an existing pyramid directory.

    Supports both traditional format (levels/) and dzsave format (slide_files/).

    Args:
        pyramid_dir: Path to the .fastpath directory

    Returns:
        PyramidStatus indicating the state
    """
    if not pyramid_dir.exists():
        return PyramidStatus.NOT_EXISTS

    # Check required files
    metadata_path = pyramid_dir / "metadata.json"
    if not metadata_path.exists():
        return PyramidStatus.INCOMPLETE

    # Validate metadata
    try:
        with open(metadata_path) as f:
            metadata = json.load(f)

        # Check required fields
        required_fields = [
            "version", "source_file", "tile_size", "dimensions", "levels"
        ]
        for field in required_fields:
            if field not in metadata:
                return PyramidStatus.CORRUPTED

        # Determine tile format (dzsave or traditional)
        tile_format = metadata.get("tile_format", "traditional")

        if tile_format == "dzsave":
            # Check slide_files directory structure
            slide_files_dir = pyramid_dir / "tiles_files"
            if not slide_files_dir.exists():
                return PyramidStatus.INCOMPLETE

            # Verify at least one level directory has tiles
            level_dirs = [d for d in slide_files_dir.iterdir() if d.is_dir() and d.name.isdigit()]
            if not level_dirs:
                return PyramidStatus.INCOMPLETE

            for level_dir in level_dirs:
                tiles = list(level_dir.glob("*.jpg"))
                if tiles:
                    break
            else:
                return PyramidStatus.INCOMPLETE
        else:
            # Traditional format: Check levels directory structure
            levels_dir = pyramid_dir / "levels"
            if not levels_dir.exists():
                return PyramidStatus.INCOMPLETE

            # Verify each level directory exists and has tiles
            for level_info in metadata["levels"]:
                level_dir = levels_dir / str(level_info["level"])
                if not level_dir.exists():
                    return PyramidStatus.INCOMPLETE

                # Check if level has at least some tiles (not empty)
                tiles = list(level_dir.glob("*.jpg"))
                if not tiles:
                    return PyramidStatus.INCOMPLETE

        # Check thumbnail exists
        if not (pyramid_dir / "thumbnail.jpg").exists():
            return PyramidStatus.INCOMPLETE

        return PyramidStatus.COMPLETE

    except (json.JSONDecodeError, KeyError, TypeError):
        return PyramidStatus.CORRUPTED


@dataclass
class PyramidMetadata:
    """Metadata for a tile pyramid."""

    version: str
    source_file: str
    source_mpp: float
    target_mpp: float
    target_magnification: float
    tile_size: int
    dimensions: tuple[int, int]
    levels: list[LevelInfo]
    background_color: tuple[int, int, int]
    preprocessed_at: str

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "source_file": self.source_file,
            "source_mpp": self.source_mpp,
            "target_mpp": self.target_mpp,
            "target_magnification": self.target_magnification,
            "tile_size": self.tile_size,
            "dimensions": list(self.dimensions),
            "levels": [
                {
                    "level": l.level,
                    "downsample": l.downsample,
                    "cols": l.cols,
                    "rows": l.rows,
                }
                for l in self.levels
            ],
            "background_color": list(self.background_color),
            "preprocessed_at": self.preprocessed_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> PyramidMetadata:
        return cls(
            version=data["version"],
            source_file=data["source_file"],
            source_mpp=data["source_mpp"],
            target_mpp=data["target_mpp"],
            target_magnification=data["target_magnification"],
            tile_size=data["tile_size"],
            dimensions=tuple(data["dimensions"]),
            levels=[
                LevelInfo(
                    level=l["level"],
                    downsample=l["downsample"],
                    cols=l["cols"],
                    rows=l["rows"],
                )
                for l in data["levels"]
            ],
            background_color=tuple(data["background_color"]),
            preprocessed_at=data["preprocessed_at"],
        )


class VipsPyramidBuilder:
    """Fast pyramid builder using pyvips dzsave() with OpenSlide level 1.

    Uses OpenSlide level 1 directly (~10x magnification) without any resizing,
    then generates tile pyramid using libvips' native Deep Zoom generator.

    Speedup: ~6x compared to standard OpenSlide + PIL pipeline.

    Requirements:
        - pyvips with OpenSlide support (libvips compiled with openslide)

    Output format:
        - tiles_files/N/col_row.jpg (Deep Zoom structure)
        - Level 0 in dzsave = lowest resolution (inverted from FastPATH convention)
    """

    def __init__(
        self,
        tile_size: int = 512,
        jpeg_quality: int = 80,
        target_mpp_override: float | None = None,
        method: str = "level1",
    ) -> None:
        """Initialize the VipsPyramidBuilder.

        Args:
            tile_size: Size of tiles in pixels (default: 512)
            jpeg_quality: JPEG quality for tiles (default: 80)
            target_mpp_override: Override MPP value when slide metadata unavailable
            method: Extraction method - "level1" (extract level 1 directly, ~MPP 1.0)
                    or "level0_resized" (extract level 0 and resize 2x to ~MPP 0.5)
        """
        if not _HAS_VIPS_OPENSLIDE:
            raise RuntimeError(
                "VipsPyramidBuilder requires pyvips with OpenSlide support. "
                "Install libvips with OpenSlide enabled."
            )

        if method not in ("level1", "level0_resized"):
            raise ValueError(f"method must be 'level1' or 'level0_resized', got '{method}'")

        self.tile_size = tile_size
        self.jpeg_quality = jpeg_quality
        self.target_mpp_override = target_mpp_override
        self.method = method

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
        levels_dir = pyramid_dir / "levels"
        levels_dir.mkdir()
        annotations_dir = pyramid_dir / "annotations"
        annotations_dir.mkdir()

        # Load slide based on selected method
        if self.method == "level1":
            # Method A: Extract level 1 directly (~MPP 1.0, ~10x)
            logger.info("Loading slide level 1 with pyvips...")
            image = pyvips.Image.openslideload(str(slide_path), level=1)
            logger.info("Loaded %s: %d x %d px", slide_path.name, image.width, image.height)
            source_mpp = self._get_mpp_at_level(slide_path, level=1)
        else:  # method == "level0_resized"
            # Method B: Extract level 0 (~MPP 0.25), resize 2x to get MPP 0.5
            logger.info("Loading slide level 0 with pyvips...")
            image = pyvips.Image.openslideload(str(slide_path), level=0)
            base_mpp = self._get_mpp_at_level(slide_path, level=0)
            logger.info("Loaded %s: %d x %d px", slide_path.name, image.width, image.height)

            # Resize 2x (halve dimensions) to get MPP 0.5
            logger.info("Resizing 2x for MPP 0.5...")
            image = image.resize(0.5, vscale=0.5, kernel="lanczos3")
            source_mpp = base_mpp * 2  # MPP doubles when dimensions halve
            logger.info("Resized to %d x %d px", image.width, image.height)

        actual_mag = 10.0 / source_mpp if source_mpp > 0 else 10.0

        dimensions = (image.width, image.height)

        # Generate thumbnail
        if progress_callback:
            progress_callback("thumbnail", 0, 1)
        logger.info("Generating thumbnail...")
        thumb = image.thumbnail_image(1024)
        thumb.jpegsave(str(pyramid_dir / "thumbnail.jpg"), Q=90)
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
            suffix=f".jpg[Q={self.jpeg_quality},interlace]",  # Progressive JPEG
            depth="onetile",  # Stop when tile fits in one tile
            layout="dz",  # Deep Zoom layout: tiles_files/level/col_row.jpg
            strip=True,  # Remove metadata for smaller/faster tiles
        )
        logger.debug("Tile pyramid generated")

        # Read dzsave output to calculate level info
        levels = self._calculate_levels_from_dzsave(pyramid_dir / "tiles_files")

        # Write metadata - use actual values from level 1
        metadata = PyramidMetadata(
            version="1.0",
            source_file=slide_path.name,
            source_mpp=source_mpp,
            target_mpp=source_mpp,  # Actual MPP at level 1
            target_magnification=actual_mag,  # Actual magnification at level 1
            tile_size=self.tile_size,
            dimensions=dimensions,
            levels=levels,
            background_color=(255, 255, 255),  # White background default
            preprocessed_at=datetime.now(timezone.utc).isoformat(),
        )

        # Add dzsave format marker to metadata
        metadata_dict = metadata.to_dict()
        metadata_dict["tile_format"] = "dzsave"

        with open(pyramid_dir / "metadata.json", "w") as f:
            json.dump(metadata_dict, f, indent=2)

        # Create empty default annotation file
        with open(annotations_dir / "default.geojson", "w") as f:
            json.dump(
                {"type": "FeatureCollection", "features": []}, f, indent=2
            )

        logger.info("Generated %d pyramid levels for %s", len(levels), slide_path.name)
        return pyramid_dir

    def _get_mpp_at_level(self, slide_path: Path, level: int) -> float:
        """Get microns-per-pixel at a specific OpenSlide level.

        Args:
            slide_path: Path to the slide file
            level: OpenSlide level index

        Returns:
            MPP value at that level, or target_mpp_override, or 1.0 as default (~10x)
        """
        try:
            image = pyvips.Image.openslideload(str(slide_path), level=0)

            # Get base MPP from level 0
            base_mpp = None
            try:
                mpp_x = image.get("openslide.mpp-x")
                if mpp_x:
                    base_mpp = float(mpp_x)
            except (ValueError, TypeError, KeyError):
                pass  # Metadata missing or invalid format
            except pyvips.error.Error:
                pass  # pyvips couldn't read the metadata

            if base_mpp is None:
                try:
                    mpp = image.get("aperio.MPP")
                    if mpp:
                        base_mpp = float(mpp)
                except (ValueError, TypeError, KeyError):
                    pass  # Metadata missing or invalid format
                except pyvips.error.Error:
                    pass  # pyvips couldn't read the metadata

            if base_mpp is None:
                # No MPP metadata - use override or default
                if self.target_mpp_override is not None:
                    return self.target_mpp_override
                return 1.0  # Default ~10x

            # Get downsample factor for the requested level
            downsample = float(image.get(f"openslide.level[{level}].downsample"))
            return base_mpp * downsample

        except (OSError, ValueError, TypeError, KeyError):
            # File I/O error or invalid metadata
            if self.target_mpp_override is not None:
                return self.target_mpp_override
            return 1.0
        except pyvips.error.Error:
            # pyvips-specific error (e.g., unsupported format)
            if self.target_mpp_override is not None:
                return self.target_mpp_override
            return 1.0

    def _calculate_levels_from_dzsave(self, dzsave_dir: Path) -> list[LevelInfo]:
        """Calculate level info from dzsave output.

        dzsave creates levels from 0 (smallest) to N (largest/full resolution).
        FastPATH expects level 0 to be the highest resolution, so we invert.

        Args:
            dzsave_dir: Path to slide_files directory created by dzsave

        Returns:
            List of LevelInfo in FastPATH order (0 = highest resolution)
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

        # dzsave level numbering: 0 = smallest, max = full resolution
        # FastPATH level numbering: 0 = full resolution
        max_dz_level = int(level_dirs[-1].name)

        levels = []
        for fastpath_level, dz_level in enumerate(range(max_dz_level, -1, -1)):
            dz_dir = dzsave_dir / str(dz_level)
            if not dz_dir.exists():
                continue

            # Count tiles to determine grid size
            tiles = list(dz_dir.glob("*.jpg"))
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
            downsample = 2 ** fastpath_level

            levels.append(LevelInfo(
                level=fastpath_level,
                downsample=downsample,
                cols=cols,
                rows=rows,
            ))

        return levels


def build_pyramid(
    slide_path: Path,
    output_dir: Path,
    tile_size: int = 512,
    jpeg_quality: int = 80,
    progress_callback: Callable[[str, int, int], None] | None = None,
    force: bool = False,
) -> Path | None:
    """Build a tile pyramid using VipsPyramidBuilder.

    Uses OpenSlide level 1 (~10x) directly with pyvips dzsave() for fast
    preprocessing.

    Args:
        slide_path: Path to WSI file
        output_dir: Output directory
        tile_size: Tile size in pixels
        jpeg_quality: JPEG quality (1-100)
        progress_callback: Progress callback function
        force: Force rebuild even if already complete

    Returns:
        Path to the created .fastpath directory, or None if skipped

    Raises:
        RuntimeError: If pyvips with OpenSlide support is not available
    """
    builder = VipsPyramidBuilder(
        tile_size=tile_size,
        jpeg_quality=jpeg_quality,
    )
    return builder.build(slide_path, output_dir, progress_callback, force=force)
