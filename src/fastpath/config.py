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

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


def _get_env_int(name: str, default: int) -> int:
    """Get an integer from environment variable with fallback."""
    value = os.environ.get(name)
    if value is not None:
        try:
            return int(value)
        except ValueError:
            logger.warning(
                "Invalid integer for %s: %r, using default %d", name, value, default
            )
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


# =============================================================================
# Preprocessing Configuration
# =============================================================================

#: VIPS internal concurrency (threads)
VIPS_CONCURRENCY: str = _get_env_str("FASTPATH_VIPS_CONCURRENCY", "8")

#: VIPS disc threshold for keeping images in RAM
VIPS_DISC_THRESHOLD: str = "3g"

#: Default parallel slides for batch preprocessing
DEFAULT_PARALLEL_SLIDES: int = 3

#: Target microns-per-pixel for preprocessed tiles (20x equivalent)
TARGET_MPP: float = 0.5

#: JPEG quality for preprocessed tiles
JPEG_QUALITY: int = 80

#: Background color for pyramid tiles (white)
BACKGROUND_COLOR: tuple[int, int, int] = (255, 255, 255)

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

#: Thumbnail JPEG quality
THUMBNAIL_JPEG_QUALITY: int = 90

#: Placeholder tile size for loading state
PLACEHOLDER_TILE_SIZE: int = 256

#: Placeholder tile color (light gray RGB)
PLACEHOLDER_COLOR: tuple[int, int, int] = (224, 224, 224)

#: RGB bytes per pixel (for stride calculations)
RGB_BYTES_PER_PIXEL: int = 3


# =============================================================================
# Validation
# =============================================================================


def _validate_config() -> None:
    """Validate configuration values and log warnings for out-of-range settings."""
    global TILE_CACHE_SIZE_MB, PREFETCH_DISTANCE, PYTHON_TILE_CACHE_SIZE

    if TILE_CACHE_SIZE_MB < 1:
        logger.warning(
            "TILE_CACHE_SIZE_MB=%d is too low, clamping to 1", TILE_CACHE_SIZE_MB
        )
        TILE_CACHE_SIZE_MB = 1

    if PREFETCH_DISTANCE < 0:
        logger.warning(
            "PREFETCH_DISTANCE=%d is negative, clamping to 0", PREFETCH_DISTANCE
        )
        PREFETCH_DISTANCE = 0

    if PYTHON_TILE_CACHE_SIZE < 1:
        logger.warning(
            "PYTHON_TILE_CACHE_SIZE=%d is too low, clamping to 1",
            PYTHON_TILE_CACHE_SIZE,
        )
        PYTHON_TILE_CACHE_SIZE = 1


_validate_config()
