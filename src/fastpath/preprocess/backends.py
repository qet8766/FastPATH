"""Image processing backend using PyVIPS.

This module provides a unified interface for image operations using PyVIPS
(libvips). PyVIPS provides significant speedups for preprocessing large WSI files:
- JPEG encode: ~5x faster than PIL
- Lanczos resize: ~4x faster than PIL
- Full pyramid generation: ~4x faster overall

Usage:
    from fastpath.preprocess.backends import VIPSBackend, is_vips_available

    img = VIPSBackend.load_jpeg(Path("input.jpg"))
    resized = VIPSBackend.resize(img, (256, 256))
    VIPSBackend.save_jpeg(resized, Path("output.jpg"), quality=95)
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np


# pyvips is imported and DLL paths are set up in fastpath/__init__.py
# This ensures warnings are suppressed before any module imports pyvips
from typing import Any

_HAS_VIPS = False
_vips_import_error: str | None = None
pyvips: Any = None

try:
    import pyvips
    _HAS_VIPS = True
except (ImportError, OSError) as e:
    _vips_import_error = str(e)


def is_vips_available() -> bool:
    """Check if PyVIPS is available.

    Returns:
        True if pyvips is installed and working
    """
    return _HAS_VIPS


def get_vips_import_error() -> str | None:
    """Get the error message if PyVIPS failed to import.

    Returns:
        Error message string, or None if pyvips is available
    """
    return _vips_import_error


class VIPSBackend:
    """PyVIPS-based image processing backend.

    This backend uses libvips via pyvips for significantly faster image
    processing. It's particularly effective for:
    - JPEG encoding (~5x faster)
    - Lanczos resampling (~4x faster)
    - Large-scale batch processing

    Requires pyvips to be installed: pip install pyvips
    On Windows, also requires libvips DLLs.
    """

    @staticmethod
    def from_numpy(arr: np.ndarray) -> "pyvips.Image":
        """Convert a numpy array to pyvips format.

        Args:
            arr: numpy array (H, W, 3) RGB uint8

        Returns:
            pyvips.Image in RGB format
        """
        if not _HAS_VIPS:
            raise RuntimeError(f"PyVIPS is not available: {_vips_import_error}")

        height, width = arr.shape[:2]
        bands = arr.shape[2] if arr.ndim == 3 else 1

        # Ensure contiguous array
        arr = np.ascontiguousarray(arr)

        vips_img = pyvips.Image.new_from_memory(
            arr.tobytes(),
            width,
            height,
            bands,
            "uchar"
        )
        return vips_img

    @staticmethod
    def to_numpy(img: "pyvips.Image") -> np.ndarray:
        """Convert a pyvips image to numpy array.

        Args:
            img: pyvips.Image

        Returns:
            numpy array (H, W, 3) RGB uint8
        """
        # Ensure RGB format (3 bands)
        if img.bands == 4:
            img = img.extract_band(0, n=3)
        elif img.bands == 1:
            # Grayscale to RGB: bandjoin joins self + list, so [img, img] gives 3 bands
            img = img.bandjoin([img, img])

        # Convert to numpy
        data = img.write_to_memory()
        return np.ndarray(
            buffer=data,
            dtype=np.uint8,
            shape=(img.height, img.width, img.bands)
        )

    @staticmethod
    def load_jpeg(path: Path) -> "pyvips.Image":
        """Load a JPEG image using sequential access for efficiency.

        Args:
            path: Path to the JPEG file

        Returns:
            pyvips.Image
        """
        if not _HAS_VIPS:
            raise RuntimeError(f"PyVIPS is not available: {_vips_import_error}")

        # Sequential access is faster for one-pass operations
        return pyvips.Image.new_from_file(str(path), access="sequential")

    @staticmethod
    def save_jpeg(img: "pyvips.Image", path: Path, quality: int = 95) -> None:
        """Save an image as JPEG.

        Args:
            img: pyvips.Image to save
            path: Output path
            quality: JPEG quality (1-100)
        """
        img.write_to_file(str(path), Q=quality)

    @staticmethod
    def save_png(img: "pyvips.Image", path: Path) -> None:
        """Save an image as PNG.

        Args:
            img: pyvips.Image to save
            path: Output path
        """
        img.write_to_file(str(path))

    @staticmethod
    def resize(img: "pyvips.Image", size: tuple[int, int]) -> "pyvips.Image":
        """Resize an image using Lanczos3 resampling.

        Args:
            img: pyvips.Image to resize
            size: Target size as (width, height)

        Returns:
            Resized pyvips.Image
        """
        target_width, target_height = size
        h_scale = target_width / img.width
        v_scale = target_height / img.height

        return img.resize(h_scale, vscale=v_scale, kernel="lanczos3")

    @staticmethod
    def composite_2x2(
        tiles: list["pyvips.Image | None"],
        tile_size: int,
        bg_color: tuple[int, int, int]
    ) -> "pyvips.Image":
        """Composite 4 tiles into a 2x2 grid using vips arrayjoin.

        Args:
            tiles: List of 4 tiles [top-left, top-right, bottom-left, bottom-right]
                   None entries are filled with background color
            tile_size: Size of each tile in pixels
            bg_color: Background color as RGB tuple

        Returns:
            Combined pyvips.Image of size (tile_size*2, tile_size*2)
        """
        if not _HAS_VIPS:
            raise RuntimeError(f"PyVIPS is not available: {_vips_import_error}")

        # Create background tile for missing tiles
        bg_tile = (
            pyvips.Image.black(tile_size, tile_size, bands=3)
            .add(bg_color)
            .cast("uchar")
        )

        # Replace None with background
        resolved_tiles = []
        for tile in tiles:
            if tile is None:
                resolved_tiles.append(bg_tile)
            else:
                # Ensure tile is the correct size
                if tile.width != tile_size or tile.height != tile_size:
                    tile = tile.resize(
                        tile_size / tile.width,
                        vscale=tile_size / tile.height,
                        kernel="lanczos3"
                    )
                resolved_tiles.append(tile)

        # Use arrayjoin for efficient 2x2 composition
        # arrayjoin expects tiles in row-major order
        return pyvips.Image.arrayjoin(resolved_tiles, across=2)

    @staticmethod
    def new_rgb(width: int, height: int, color: tuple[int, int, int]) -> "pyvips.Image":
        """Create a new RGB image filled with a solid color.

        Args:
            width: Image width
            height: Image height
            color: RGB tuple (0-255 each)

        Returns:
            pyvips.Image filled with the color
        """
        if not _HAS_VIPS:
            raise RuntimeError(f"PyVIPS is not available: {_vips_import_error}")

        return (
            pyvips.Image.black(width, height, bands=3)
            .add(color)
            .cast("uchar")
        )


def get_backend() -> type[VIPSBackend]:
    """Get the image processing backend.

    Returns:
        VIPSBackend class

    Raises:
        RuntimeError: If PyVIPS is not available
    """
    if not _HAS_VIPS:
        raise RuntimeError(
            f"PyVIPS is required but not available: {_vips_import_error}\n"
            "Install pyvips and libvips: pip install pyvips\n"
            "On Windows, also install libvips DLLs from: "
            "https://github.com/libvips/build-win64-mxe/releases"
        )
    return VIPSBackend


def get_backend_name() -> str:
    """Get the name of the backend.

    Returns:
        "PyVIPS"
    """
    return "PyVIPS"


# Convenience function for setting VIPS concurrency
def set_vips_concurrency(num_threads: int) -> None:
    """Set the number of threads VIPS uses internally.

    This affects VIPS's internal parallelism, separate from Python's
    ThreadPoolExecutor workers.

    Args:
        num_threads: Number of threads for VIPS operations

    Raises:
        RuntimeError: If PyVIPS is not available
    """
    if not _HAS_VIPS:
        raise RuntimeError("PyVIPS is not available")

    # cache_set_max sets max number of operations to cache (not memory size)
    pyvips.cache_set_max(1000)
    os.environ["VIPS_CONCURRENCY"] = str(num_threads)
