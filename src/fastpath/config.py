"""Centralized configuration for FastPATH.

All tunable parameters are defined here with sensible defaults.
Values can be overridden via environment variables.

Environment Variables:
    FASTPATH_VIPS_PATH: Base path for VIPS installation (default: C:/vips)
    FASTPATH_TILE_CACHE_MB: Rust scheduler tile cache size in MB (default: 12288)
    FASTPATH_PREFETCH_DISTANCE: Tiles to prefetch ahead (default: 3)
    FASTPATH_PYTHON_CACHE_SIZE: Python tile cache size in tiles (default: 256)
    FASTPATH_VIPS_CONCURRENCY: VIPS internal thread count (default: 8)
"""

from __future__ import annotations

import os
from pathlib import Path


def _get_env_int(name: str, default: int) -> int:
    """Get an integer from environment variable with fallback."""
    value = os.environ.get(name)
    if value is not None:
        try:
            return int(value)
        except ValueError:
            pass
    return default


def _get_env_str(name: str, default: str) -> str:
    """Get a string from environment variable with fallback."""
    return os.environ.get(name, default)


def _get_env_path(name: str, default: str) -> Path:
    """Get a Path from environment variable with fallback."""
    return Path(os.environ.get(name, default))


# =============================================================================
# VIPS / DLL Configuration (Windows)
# =============================================================================

#: Base path for VIPS installation on Windows
VIPS_BASE_PATH: Path = _get_env_path("FASTPATH_VIPS_PATH", "C:/vips")

#: DLLs to preload for VIPS/OpenSlide support
VIPS_REQUIRED_DLLS: tuple[str, ...] = ("libopenslide-1.dll", "libvips-42.dll")


# =============================================================================
# Tile Cache Configuration
# =============================================================================

#: Rust tile scheduler cache size in MB (default: 12GB)
TILE_CACHE_SIZE_MB: int = _get_env_int("FASTPATH_TILE_CACHE_MB", 12288)

#: Number of tiles to prefetch in pan direction
PREFETCH_DISTANCE: int = _get_env_int("FASTPATH_PREFETCH_DISTANCE", 3)

#: Python-side LRU tile cache size (number of tiles)
PYTHON_TILE_CACHE_SIZE: int = _get_env_int("FASTPATH_PYTHON_CACHE_SIZE", 256)


# =============================================================================
# Tile Generation Defaults
# =============================================================================

#: Default tile size in pixels
DEFAULT_TILE_SIZE: int = 512

#: Default JPEG quality for tiles
DEFAULT_JPEG_QUALITY: int = 80

#: Default target MPP when metadata unavailable
DEFAULT_TARGET_MPP: float = 1.0


# =============================================================================
# Preprocessing Configuration
# =============================================================================

#: VIPS internal concurrency (threads)
VIPS_CONCURRENCY: str = _get_env_str("FASTPATH_VIPS_CONCURRENCY", "8")

#: VIPS disc threshold for keeping images in RAM
VIPS_DISC_THRESHOLD: str = "3g"

#: Default parallel slides for batch preprocessing
DEFAULT_PARALLEL_SLIDES: int = 3

#: Supported WSI file extensions
WSI_EXTENSIONS: frozenset[str] = frozenset({
    ".svs", ".ndpi", ".tif", ".tiff", ".mrxs", ".vms", ".vmu", ".scn"
})


# =============================================================================
# UI Configuration
# =============================================================================

#: Maximum recent files to remember
MAX_RECENT_FILES: int = 10

#: Thumbnail maximum dimension
THUMBNAIL_MAX_SIZE: int = 1024
