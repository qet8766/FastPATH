"""Image providers for QML."""

from __future__ import annotations

import logging
import threading
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
    from fastpath.core.annotations import AnnotationManager
    from fastpath.core.slide import SlideManager


class TileImageProvider(QQuickImageProvider):
    """Provides tile images to QML.

    URL format: image://tiles/{level}/{col}_{row}

    Uses the Rust scheduler for high-performance tile loading.
    """

    def __init__(self, rust_scheduler: RustTileScheduler) -> None:
        super().__init__(QQuickImageProvider.ImageType.Image)
        self._rust_scheduler = rust_scheduler
        self._placeholder = self._create_placeholder()

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
            # Strip query string (e.g. "?g=1" used for cache-busting on slide switch)
            url_part, _, _ = id.partition("?")

            parts = url_part.split("/")
            if len(parts) != 2:
                return self._placeholder

            level = int(parts[0])
            col_row = parts[1].split("_")
            if len(col_row) != 2:
                return self._placeholder

            col = int(col_row[0])
            row = int(col_row[1])

            if not self._rust_scheduler.is_loaded:
                return self._placeholder

            tile_data = self._rust_scheduler.get_tile(level, col, row)
            if tile_data is None:
                logger.warning(
                    "Tile request failed: level=%d col=%d row=%d - scheduler returned None (is_loaded=%s)",
                    level, col, row, self._rust_scheduler.is_loaded
                )
                return self._placeholder

            logger.debug("Tile loaded: level=%d col=%d row=%d", level, col, row)
            data, width, height = tile_data
            # Convert raw RGB bytes to QImage
            image = QImage(
                data,
                width,
                height,
                width * RGB_BYTES_PER_PIXEL,
                QImage.Format.Format_RGB888,
            )
            # Make a copy since the data buffer may be reused
            image = image.copy()
            return image

        except (ValueError, IndexError):
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
            # Parse URL: "level/col_row?g=generation"
            url_part, _, query = id.partition("?")
            parts = url_part.split("/")
            if len(parts) != 2:
                return QImage()

            level = int(parts[0])
            col_row = parts[1].split("_")
            if len(col_row) != 2:
                return QImage()
            col = int(col_row[0])
            row = int(col_row[1])

            generation = 0
            if query.startswith("g="):
                generation = int(query[2:])

            tile_size = self._slide_manager.tileSize if self._slide_manager.isLoaded else DEFAULT_TILE_SIZE

            # Check LRU cache
            cache_key = (level, col, row, generation)
            with self._cache_lock:
                if cache_key in self._cache:
                    self._cache.move_to_end(cache_key)
                    return self._cache[cache_key]

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
                with self._cache_lock:
                    self._cache[cache_key] = result
                    if len(self._cache) > self.CACHE_SIZE:
                        self._cache.popitem(last=False)
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
            with self._cache_lock:
                self._cache[cache_key] = qimage
                if len(self._cache) > self.CACHE_SIZE:
                    self._cache.popitem(last=False)

            return qimage

        except (ValueError, IndexError):
            return QImage()
