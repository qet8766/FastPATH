"""Qt models for QML bindings."""

from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import (
    QAbstractListModel,
    QModelIndex,
    QObject,
    Qt,
    Signal,
    Slot,
    Property,
)

logger = logging.getLogger(__name__)


class TileModel(QAbstractListModel):
    """Model for visible tiles in the viewport.

    Provides tile data to QML ListView/Repeater for rendering.
    """

    LevelRole = Qt.ItemDataRole.UserRole + 1
    ColRole = Qt.ItemDataRole.UserRole + 2
    RowRole = Qt.ItemDataRole.UserRole + 3
    XRole = Qt.ItemDataRole.UserRole + 4
    YRole = Qt.ItemDataRole.UserRole + 5
    WidthRole = Qt.ItemDataRole.UserRole + 6
    HeightRole = Qt.ItemDataRole.UserRole + 7
    SourceRole = Qt.ItemDataRole.UserRole + 8

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._tiles: list[dict] = []

    def hasTiles(self) -> bool:
        """Check if there are any tiles in the model."""
        return bool(self._tiles)

    def getTiles(self) -> list[dict]:
        """Get a copy of the current tiles list."""
        return list(self._tiles)

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self._tiles)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        """Return data for the given model index and role.

        This is the core Qt model method called by QML views to retrieve
        tile information for rendering.

        Args:
            index: Model index specifying which tile row
            role: Data role (LevelRole, ColRole, RowRole, XRole, etc.)

        Returns:
            The requested data value, or None if index is invalid
        """
        if not index.isValid() or index.row() >= len(self._tiles):
            return None

        tile = self._tiles[index.row()]
        if role == self.LevelRole:
            return tile["level"]
        elif role == self.ColRole:
            return tile["col"]
        elif role == self.RowRole:
            return tile["row"]
        elif role == self.XRole:
            return tile["x"]
        elif role == self.YRole:
            return tile["y"]
        elif role == self.WidthRole:
            return tile["width"]
        elif role == self.HeightRole:
            return tile["height"]
        elif role == self.SourceRole:
            return tile["source"]
        return None

    def roleNames(self) -> dict:
        return {
            self.LevelRole: b"level",
            self.ColRole: b"col",
            self.RowRole: b"row",
            self.XRole: b"tileX",
            self.YRole: b"tileY",
            self.WidthRole: b"tileWidth",
            self.HeightRole: b"tileHeight",
            self.SourceRole: b"tileSource",
        }

    @Slot(list)
    def batchUpdate(self, tiles: list) -> None:
        """Atomically replace tiles with single model reset.

        This method reduces QML re-renders by emitting a single signal
        instead of per-tile insert/remove signals.

        Args:
            tiles: List of dicts with keys: level, col, row, x, y, width, height, source
        """
        new_keys = frozenset((t["level"], t["col"], t["row"]) for t in tiles)
        old_keys = frozenset((t["level"], t["col"], t["row"]) for t in self._tiles)

        if new_keys == old_keys:
            return  # Skip - same tiles visible

        logger.info("TileModel.batchUpdate: %d tiles (levels: %s)",
                    len(tiles), sorted(set(t["level"] for t in tiles)) if tiles else [])

        self.beginResetModel()
        self._tiles = list(tiles)
        self.endResetModel()

    @Slot()
    def clear(self) -> None:
        """Clear all tiles."""
        self.beginResetModel()
        self._tiles = []
        self.endResetModel()


class RecentFilesModel(QAbstractListModel):
    """Model for recent files list."""

    PathRole = Qt.ItemDataRole.UserRole + 1
    NameRole = Qt.ItemDataRole.UserRole + 2

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._files: list[dict] = []

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self._files)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or index.row() >= len(self._files):
            return None

        file = self._files[index.row()]
        if role == self.PathRole:
            return file["path"]
        elif role == self.NameRole:
            return file["name"]
        return None

    def roleNames(self) -> dict:
        return {
            self.PathRole: b"filePath",
            self.NameRole: b"fileName",
        }

    @Slot(str, str)
    def addFile(self, path: str, name: str) -> None:
        """Add a file to the recent list."""
        # Remove if already exists
        self._files = [f for f in self._files if f["path"] != path]

        # Add to front
        self.beginInsertRows(QModelIndex(), 0, 0)
        self._files.insert(0, {"path": path, "name": name})
        self.endInsertRows()

        # Limit to 10 files
        if len(self._files) > 10:
            self.beginRemoveRows(QModelIndex(), 10, len(self._files) - 1)
            self._files = self._files[:10]
            self.endRemoveRows()

    @Slot()
    def clear(self) -> None:
        """Clear the recent files list."""
        self.beginResetModel()
        self._files = []
        self.endResetModel()
