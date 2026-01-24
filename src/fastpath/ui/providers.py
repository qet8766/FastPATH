"""Image providers for QML."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QImage
from PySide6.QtQuick import QQuickImageProvider

from fastpath.config import PLACEHOLDER_TILE_SIZE, PLACEHOLDER_COLOR, RGB_BYTES_PER_PIXEL
from fastpath_core import RustTileScheduler

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
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
            parts = id.split("/")
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
