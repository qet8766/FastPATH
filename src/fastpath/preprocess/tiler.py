"""Tile extraction from whole-slide images using OpenSlide.

.. deprecated::
    This module is DEPRECATED and not actively used. FastPATH now uses
    pyvips dzsave() for tile generation (see pyramid.py), which is ~6x faster.

    This module remains for reference and potential future use cases where
    direct OpenSlide access is needed (e.g., custom tile extraction logic).
    It may be removed in a future version.
"""

from __future__ import annotations

import ctypes
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import numpy as np
from PIL import Image


def _setup_openslide_dll_paths() -> None:
    """Set up DLL search paths for OpenSlide on Windows.

    Checks for libopenslide in C:/vips/vips-dev-* installation.
    Must be called BEFORE importing openslide.
    """
    if sys.platform != "win32":
        return

    vips_base = Path("C:/vips")
    if not vips_base.exists():
        return

    vips_dirs = list(vips_base.glob("vips-dev-*"))
    if not vips_dirs:
        return

    vips_bin = vips_dirs[0] / "bin"
    if not vips_bin.exists():
        return

    # Add DLL directory
    if hasattr(os, "add_dll_directory"):
        os.add_dll_directory(str(vips_bin))

    # Pre-load OpenSlide DLL
    openslide_dll = vips_bin / "libopenslide-1.dll"
    if openslide_dll.exists():
        try:
            ctypes.CDLL(str(openslide_dll))
        except OSError:
            pass


# Set up DLL paths before importing openslide
_setup_openslide_dll_paths()


try:
    import openslide
except ImportError:
    openslide = None


@dataclass
class TileCoord:
    """Represents a tile coordinate in the pyramid."""

    level: int
    col: int
    row: int

    @property
    def filename(self) -> str:
        return f"{self.col}_{self.row}.jpg"


@dataclass
class TileInfo:
    """Information about a tile including its image data."""

    coord: TileCoord
    image: Image.Image


class TileExtractor:
    """Extracts tiles from whole-slide images at a target magnification.

    Args:
        slide_path: Path to the WSI file (SVS, NDPI, etc.)
        tile_size: Size of tiles in pixels (default: 512)
        target_mpp: Target microns per pixel (0.5 = 20x magnification)
    """

    def __init__(
        self,
        slide_path: Path,
        tile_size: int = 512,
        target_mpp: float = 0.5,
    ) -> None:
        if openslide is None:
            raise ImportError(
                "openslide-python is required. Install with: pip install openslide-python"
            )

        self.slide_path = Path(slide_path)
        self.tile_size = tile_size
        self.target_mpp = target_mpp

        self._slide = openslide.OpenSlide(str(self.slide_path))
        self._source_mpp = self._get_mpp()
        self._downsample = self.target_mpp / self._source_mpp
        self._best_level = self._slide.get_best_level_for_downsample(self._downsample)

    def _get_mpp(self) -> float:
        """Get microns per pixel from slide metadata."""
        mpp_x = self._slide.properties.get(openslide.PROPERTY_NAME_MPP_X)
        mpp_y = self._slide.properties.get(openslide.PROPERTY_NAME_MPP_Y)

        if mpp_x is not None and mpp_y is not None:
            return (float(mpp_x) + float(mpp_y)) / 2

        # Fallback: assume 40x = 0.25 mpp
        objective = self._slide.properties.get(
            openslide.PROPERTY_NAME_OBJECTIVE_POWER, "40"
        )
        return 10.0 / float(objective)

    @property
    def source_mpp(self) -> float:
        """Source microns per pixel."""
        return self._source_mpp

    @property
    def dimensions(self) -> tuple[int, int]:
        """Dimensions at target MPP (width, height)."""
        w, h = self._slide.dimensions
        scale = self._source_mpp / self.target_mpp
        return int(w * scale), int(h * scale)

    @property
    def num_cols(self) -> int:
        """Number of tile columns."""
        return (self.dimensions[0] + self.tile_size - 1) // self.tile_size

    @property
    def num_rows(self) -> int:
        """Number of tile rows."""
        return (self.dimensions[1] + self.tile_size - 1) // self.tile_size

    @property
    def background_color(self) -> tuple[int, int, int]:
        """Background color from slide metadata."""
        bg = self._slide.properties.get(openslide.PROPERTY_NAME_BACKGROUND_COLOR)
        if bg:
            return tuple(int(bg[i : i + 2], 16) for i in (0, 2, 4))
        return (255, 255, 255)

    def get_thumbnail(self, max_size: int = 1024) -> Image.Image:
        """Get slide thumbnail."""
        return self._slide.get_thumbnail((max_size, max_size))

    def extract_tile(self, col: int, row: int) -> Image.Image:
        """Extract a single tile at the target MPP.

        Args:
            col: Column index (0-based)
            row: Row index (0-based)

        Returns:
            PIL Image of the tile (tile_size x tile_size, RGB)
        """
        # Calculate position in level 0 coordinates
        level_downsample = self._slide.level_downsamples[self._best_level]
        effective_scale = self._downsample / level_downsample

        # Size to read from the best level
        read_size = int(self.tile_size * effective_scale)

        # Position in level 0 coordinates
        x0 = int(col * self.tile_size * self._downsample)
        y0 = int(row * self.tile_size * self._downsample)

        # Read region
        region = self._slide.read_region((x0, y0), self._best_level, (read_size, read_size))
        region = region.convert("RGB")

        # Resize to target tile size if needed
        if region.size != (self.tile_size, self.tile_size):
            region = region.resize(
                (self.tile_size, self.tile_size), Image.Resampling.LANCZOS
            )

        # Handle edge tiles - pad with background if undersized
        w, h = self.dimensions
        tile_right = (col + 1) * self.tile_size
        tile_bottom = (row + 1) * self.tile_size

        if tile_right > w or tile_bottom > h:
            # Create background-filled tile
            padded = Image.new("RGB", (self.tile_size, self.tile_size), self.background_color)
            # Calculate actual tile size
            actual_w = min(self.tile_size, w - col * self.tile_size)
            actual_h = min(self.tile_size, h - row * self.tile_size)
            # Crop and paste
            cropped = region.crop((0, 0, actual_w, actual_h))
            padded.paste(cropped, (0, 0))
            return padded

        return region

    def iter_tiles(self) -> Iterator[TileInfo]:
        """Iterate over all tiles.

        Yields:
            TileInfo for each tile
        """
        for row in range(self.num_rows):
            for col in range(self.num_cols):
                coord = TileCoord(level=0, col=col, row=row)
                image = self.extract_tile(col, row)
                yield TileInfo(coord=coord, image=image)

    def close(self) -> None:
        """Close the slide file."""
        self._slide.close()

    def __enter__(self) -> TileExtractor:
        return self

    def __exit__(self, *args) -> None:
        self.close()
