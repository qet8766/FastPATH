"""Image providers for QML."""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import OrderedDict
from typing import TYPE_CHECKING

from PIL import Image as PILImage, ImageDraw

from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QImage
from PySide6.QtQuick import QQuickImageProvider

from fastpath.config import PLACEHOLDER_TILE_SIZE, PLACEHOLDER_COLOR, RGB_BYTES_PER_PIXEL, DEFAULT_TILE_SIZE
from fastpath_core import RustTileScheduler

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from fastpath.ui.annotations import AnnotationManager
    from fastpath.ui.slide import SlideManager


def _parse_tile_url(id: str) -> tuple[int, int, int, int] | None:
    """Parse a tile URL of the form 'level/col_row?g=generation'.

    Returns (level, col, row, generation) or None if invalid.
    """
    url_part, _, query = id.partition("?")
    parts = url_part.split("/")
    if len(parts) != 2:
        return None

    level = int(parts[0])
    col_row = parts[1].split("_")
    if len(col_row) != 2:
        return None

    col = int(col_row[0])
    row = int(col_row[1])

    generation = 0
    if query.startswith("g="):
        generation = int(query[2:])

    return (level, col, row, generation)


class TileImageProvider(QQuickImageProvider):
    """Provides tile images to QML.

    URL format: image://tiles/{level}/{col}_{row}

    Uses the Rust scheduler for high-performance tile loading.
    """

    def __init__(self, rust_scheduler: RustTileScheduler) -> None:
        super().__init__(QQuickImageProvider.ImageType.Image)
        self._rust_scheduler = rust_scheduler
        self._placeholder = self._create_placeholder()
        tile_mode_env = os.environ.get("FASTPATH_TILE_MODE", "rgb").strip().lower()
        self._tile_mode = "jpeg" if tile_mode_env in {"jpeg", "jpg"} else "rgb"
        if self._tile_mode == "jpeg" and not hasattr(self._rust_scheduler, "get_tile_jpeg"):
            logger.warning(
                "FASTPATH_TILE_MODE=%r requested but Rust extension does not expose get_tile_jpeg(); "
                "falling back to rgb",
                tile_mode_env,
            )
            self._tile_mode = "rgb"
        # `QImage(data, ...)` wraps the provided buffer. Copying forces QImage to
        # own its pixels (safe but expensive). PySide6 keeps the Python buffer
        # alive for the lifetime of the QImage, so skipping the copy avoids an
        # extra full-tile memcpy per request.
        # Default to the zero-copy Rust buffer path (if available). It can be
        # disabled for debugging with FASTPATH_TILE_BUFFER=0.
        tile_buf_env = os.environ.get("FASTPATH_TILE_BUFFER")
        self._use_tile_buffer = (
            True
            if tile_buf_env is None
            else tile_buf_env.strip().lower() in {"1", "true", "yes"}
        )
        self._force_qimage_copy = (
            os.environ.get("FASTPATH_FORCE_QIMAGE_COPY", "").strip().lower()
            in {"1", "true", "yes"}
        )
        self._timing_enabled = (
            os.environ.get("FASTPATH_QIMAGE_TIMING", "").strip().lower()
            in {"1", "true", "yes"}
        )
        self._timing_every = int(os.environ.get("FASTPATH_QIMAGE_TIMING_EVERY", "100"))
        self._timing_lock = threading.Lock()
        self._timing_count = 0
        self._timing_rust_s = 0.0
        self._timing_qimage_s = 0.0
        self._timing_copy_s = 0.0

    def _create_placeholder(self) -> QImage:
        """Create a neutral placeholder image for loading tiles."""
        placeholder = QImage(
            PLACEHOLDER_TILE_SIZE, PLACEHOLDER_TILE_SIZE, QImage.Format.Format_RGB888
        )
        placeholder.fill(QColor(*PLACEHOLDER_COLOR))
        return placeholder

    def requestImage(
        self, id: str, size: QSize, requested_size: QSize  # noqa: ARG002
    ) -> QImage:
        """Load a tile image.

        Args:
            id: Tile identifier in format "level/col_row"
            size: Output size reference (unused - Qt requires this parameter)
            requested_size: Requested size (unused - we return full tile size)

        Returns:
            QImage of the tile
        """
        try:
            parsed = _parse_tile_url(id)
            if parsed is None:
                return self._placeholder
            level, col, row, _ = parsed

            if not self._rust_scheduler.is_loaded:
                return self._placeholder

            t0 = time.perf_counter() if self._timing_enabled else 0.0
            tile_data = None
            if self._tile_mode == "jpeg":
                tile_data = self._rust_scheduler.get_tile_jpeg(level, col, row)
            elif self._use_tile_buffer and hasattr(self._rust_scheduler, "get_tile_buffer"):
                tile_data = self._rust_scheduler.get_tile_buffer(level, col, row)
            else:
                tile_data = self._rust_scheduler.get_tile(level, col, row)
            t1 = time.perf_counter() if self._timing_enabled else 0.0
            if tile_data is None:
                logger.warning(
                    "Tile request failed: level=%d col=%d row=%d - scheduler returned None (is_loaded=%s)",
                    level, col, row, self._rust_scheduler.is_loaded
                )
                return self._placeholder

            logger.debug("Tile loaded: level=%d col=%d row=%d", level, col, row)
            if self._tile_mode == "jpeg":
                image = QImage.fromData(tile_data, "JPG")
                if image.isNull():
                    logger.warning(
                        "JPEG decode failed: level=%d col=%d row=%d - falling back to RGB path",
                        level,
                        col,
                        row,
                    )
                    if self._use_tile_buffer and hasattr(
                        self._rust_scheduler, "get_tile_buffer"
                    ):
                        rgb = self._rust_scheduler.get_tile_buffer(level, col, row)
                    else:
                        rgb = self._rust_scheduler.get_tile(level, col, row)
                    if rgb is None:
                        return self._placeholder
                    data, width, height = rgb
                    image = QImage(
                        data,
                        width,
                        height,
                        width * RGB_BYTES_PER_PIXEL,
                        QImage.Format.Format_RGB888,
                    )
            else:
                data, width, height = tile_data
                # Convert raw RGB bytes to QImage
                image = QImage(
                    data,
                    width,
                    height,
                    width * RGB_BYTES_PER_PIXEL,
                    QImage.Format.Format_RGB888,
                )
            t2 = time.perf_counter() if self._timing_enabled else 0.0
            if self._force_qimage_copy:
                image = image.copy()
            t3 = time.perf_counter() if self._timing_enabled else 0.0

            if self._timing_enabled:
                with self._timing_lock:
                    self._timing_count += 1
                    self._timing_rust_s += (t1 - t0)
                    self._timing_qimage_s += (t2 - t1)
                    self._timing_copy_s += (t3 - t2)
                    if self._timing_count % self._timing_every == 0:
                        n = self._timing_count
                        logger.info(
                            "TileImageProvider timing over %d tiles: rust=%.3fms qimage=%.3fms copy=%.3fms (avg)",
                            n,
                            (self._timing_rust_s / n) * 1000.0,
                            (self._timing_qimage_s / n) * 1000.0,
                            (self._timing_copy_s / n) * 1000.0,
                        )
            return image

        except Exception:
            logger.exception("TileImageProvider.requestImage failed: id=%r", id)
            return self._placeholder


class ThumbnailProvider(QQuickImageProvider):
    """Provides thumbnail images to QML.

    URL format:
        image://thumbnail/slide - slide thumbnail
    """

    def __init__(self, slide_manager: SlideManager) -> None:
        super().__init__(QQuickImageProvider.ImageType.Image)
        self._slide_manager = slide_manager

    def requestImage(
        self, id: str, size: QSize, requested_size: QSize  # noqa: ARG002
    ) -> QImage:
        """Load thumbnail image.

        Args:
            id: Thumbnail identifier ("slide" for slide thumbnail)
            size: Output size reference (unused - Qt requires this parameter)
            requested_size: Requested size (unused - we return full thumbnail)

        Returns:
            QImage of the thumbnail, or empty QImage if not found or invalid id
        """
        if id == "slide":
            path = self._slide_manager.getThumbnailPath()
        else:
            return QImage()

        if not path:
            return QImage()

        image = QImage(path)
        if image.isNull():
            return QImage()

        return image


def _parse_hex_color(hex_color: str) -> tuple[int, int, int]:
    """Parse a hex color string to (r, g, b) tuple."""
    hex_color = hex_color.lstrip("#")
    if len(hex_color) == 6:
        return (int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16))
    return (255, 107, 107)  # default annotation color


class AnnotationTileImageProvider(QQuickImageProvider):
    """Provides rasterized annotation tile images to QML.

    URL format: image://annotations/{level}/{col}_{row}?g={generation}

    Rasterizes annotations into tile-sized RGBA images using PIL.
    Uses an LRU cache keyed on (level, col, row, generation) for performance.
    """

    CACHE_SIZE = 512
    FILL_ALPHA = 102  # ~40% of 255
    STROKE_WIDTH = 2

    def __init__(
        self,
        annotation_manager: AnnotationManager,
        slide_manager: SlideManager,
    ) -> None:
        super().__init__(QQuickImageProvider.ImageType.Image)
        self._annotation_manager = annotation_manager
        self._slide_manager = slide_manager
        self._cache: OrderedDict[tuple[int, int, int, int], QImage] = OrderedDict()
        self._cache_lock = threading.Lock()
        self._transparent_tile: QImage | None = None

    def _get_transparent_tile(self, tile_size: int) -> QImage:
        """Return a cached transparent tile of the given size."""
        if self._transparent_tile is None or self._transparent_tile.width() != tile_size:
            img = QImage(tile_size, tile_size, QImage.Format.Format_RGBA8888)
            img.fill(QColor(0, 0, 0, 0))
            self._transparent_tile = img
        return self._transparent_tile

    def _cache_get(self, key: tuple[int, int, int, int]) -> QImage | None:
        """Get from LRU cache (promotes to end)."""
        with self._cache_lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
        return None

    def _cache_put(self, key: tuple[int, int, int, int], value: QImage) -> None:
        """Put into LRU cache (evicts oldest if over capacity)."""
        with self._cache_lock:
            self._cache[key] = value
            if len(self._cache) > self.CACHE_SIZE:
                self._cache.popitem(last=False)

    def requestImage(
        self, id: str, size: QSize, requested_size: QSize  # noqa: ARG002
    ) -> QImage:
        """Rasterize annotations for a single tile.

        Args:
            id: Tile identifier in format "level/col_row?g=generation"
            size: Output size reference (unused)
            requested_size: Requested size (unused)

        Returns:
            QImage with annotations rendered as RGBA
        """
        try:
            parsed = _parse_tile_url(id)
            if parsed is None:
                return QImage()
            level, col, row, generation = parsed

            tile_size = self._slide_manager.tileSize if self._slide_manager.isLoaded else DEFAULT_TILE_SIZE

            # Check LRU cache
            cache_key = (level, col, row, generation)
            cached = self._cache_get(cache_key)
            if cached is not None:
                return cached

            # Get downsample for this level
            if not self._slide_manager.isLoaded:
                return self._get_transparent_tile(tile_size)

            level_info = self._slide_manager.getLevelInfo(level)
            downsample = level_info[0]

            # Compute tile bounds in slide space (level 0 coordinates)
            tile_x = col * tile_size * downsample
            tile_y = row * tile_size * downsample
            tile_w = tile_size * downsample
            tile_h = tile_size * downsample

            # Query annotations in this tile's spatial extent
            annotations = self._annotation_manager.queryViewport(tile_x, tile_y, tile_w, tile_h)

            if not annotations:
                result = self._get_transparent_tile(tile_size)
                self._cache_put(cache_key, result)
                return result

            # Rasterize with PIL
            pil_img = PILImage.new("RGBA", (tile_size, tile_size), (0, 0, 0, 0))
            draw = ImageDraw.Draw(pil_img)

            for ann in annotations:
                r, g, b = _parse_hex_color(ann.get("color", "#ff6b6b"))
                fill_color = (r, g, b, self.FILL_ALPHA)
                stroke_color = (r, g, b, 255)
                ann_type = ann.get("type", "polygon")
                coords = ann.get("coordinates", [])

                if ann_type == "point" and coords:
                    # Draw circle for points
                    px = (coords[0][0] - tile_x) / downsample
                    py = (coords[0][1] - tile_y) / downsample
                    radius = 6
                    draw.ellipse(
                        [px - radius, py - radius, px + radius, py + radius],
                        fill=fill_color,
                        outline=stroke_color,
                        width=self.STROKE_WIDTH,
                    )
                elif ann_type == "rectangle" and len(coords) >= 2:
                    x1 = (coords[0][0] - tile_x) / downsample
                    y1 = (coords[0][1] - tile_y) / downsample
                    x2 = (coords[1][0] - tile_x) / downsample
                    y2 = (coords[1][1] - tile_y) / downsample
                    draw.rectangle(
                        [x1, y1, x2, y2],
                        fill=fill_color,
                        outline=stroke_color,
                        width=self.STROKE_WIDTH,
                    )
                elif len(coords) >= 3:
                    # Polygon or freehand
                    poly_points = [
                        ((c[0] - tile_x) / downsample, (c[1] - tile_y) / downsample)
                        for c in coords
                    ]
                    draw.polygon(poly_points, fill=fill_color, outline=stroke_color)

            # Convert PIL RGBA to QImage
            raw_data = pil_img.tobytes("raw", "RGBA")
            qimage = QImage(
                raw_data, tile_size, tile_size,
                tile_size * 4,
                QImage.Format.Format_RGBA8888,
            )
            qimage = qimage.copy()  # Detach from raw_data buffer

            # Cache result
            self._cache_put(cache_key, qimage)

            return qimage

        except (ValueError, IndexError):
            return QImage()
