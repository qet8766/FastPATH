"""Qt models for QML bindings."""

from __future__ import annotations

import logging
from pathlib import Path
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

from fastpath.config import MAX_RECENT_FILES

logger = logging.getLogger(__name__)

# Status constants for file processing (Python-side only; QML uses string literals)
STATUS_PENDING = "pending"
STATUS_PROCESSING = "processing"
STATUS_DONE = "done"
STATUS_SKIPPED = "skipped"
STATUS_ERROR = "error"


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

    _ROLE_KEYS: dict[int, str] = {
        LevelRole: "level",
        ColRole: "col",
        RowRole: "row",
        XRole: "x",
        YRole: "y",
        WidthRole: "width",
        HeightRole: "height",
        SourceRole: "source",
    }

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._tiles: list[dict] = []
        self._tiles_key_cache: frozenset[tuple[int, int, int]] | None = None

    def hasTiles(self) -> bool:
        """Check if there are any tiles in the model."""
        return bool(self._tiles)

    def getTiles(self) -> list[dict]:
        """Get a copy of the current tiles list."""
        return list(self._tiles)

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self._tiles)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        """Return data for the given model index and role."""
        if not index.isValid() or index.row() >= len(self._tiles):
            return None
        key = self._ROLE_KEYS.get(role)
        return self._tiles[index.row()][key] if key else None

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
        instead of per-tile insert/remove signals. Uses cached frozenset
        to avoid recomputing tile keys on every update.

        Args:
            tiles: List of dicts with keys: level, col, row, x, y, width, height, source
        """
        new_keys = frozenset((t["level"], t["col"], t["row"]) for t in tiles)

        if new_keys == self._tiles_key_cache:
            return  # Skip - same tiles visible

        logger.info("TileModel.batchUpdate: %d tiles (levels: %s)",
                    len(tiles), sorted(set(t["level"] for t in tiles)) if tiles else [])

        self.beginResetModel()
        self._tiles = list(tiles)
        self._tiles_key_cache = new_keys
        self.endResetModel()

    @Slot()
    def clear(self) -> None:
        """Clear all tiles."""
        self.beginResetModel()
        self._tiles = []
        self._tiles_key_cache = None
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

        # Limit to max recent files
        if len(self._files) > MAX_RECENT_FILES:
            self.beginRemoveRows(QModelIndex(), MAX_RECENT_FILES, len(self._files) - 1)
            self._files = self._files[:MAX_RECENT_FILES]
            self.endRemoveRows()

    @Slot()
    def clear(self) -> None:
        """Clear the recent files list."""
        self.beginResetModel()
        self._files = []
        self.endResetModel()


class FileListModel(QAbstractListModel):
    """Model for batch preprocessing file list with status and progress.

    Each file entry tracks:
    - fileName: Display name of the file
    - filePath: Full path to the file
    - status: pending | processing | done | skipped | error
    - progress: 0.0-1.0 progress value
    - errorMessage: Error details if status is 'error'
    """

    FileNameRole = Qt.ItemDataRole.UserRole + 1
    FilePathRole = Qt.ItemDataRole.UserRole + 2
    StatusRole = Qt.ItemDataRole.UserRole + 3
    ProgressRole = Qt.ItemDataRole.UserRole + 4
    ErrorMessageRole = Qt.ItemDataRole.UserRole + 5

    _ROLE_KEYS: dict[int, str] = {
        FileNameRole: "fileName",
        FilePathRole: "filePath",
        StatusRole: "status",
        ProgressRole: "progress",
        ErrorMessageRole: "errorMessage",
    }

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._files: list[dict] = []

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self._files)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or index.row() >= len(self._files):
            return None
        key = self._ROLE_KEYS.get(role)
        if key is None:
            return None
        return self._files[index.row()].get(key, "")

    def _valid_index(self, index: int) -> bool:
        """Check if index is within the file list bounds."""
        return 0 <= index < len(self._files)

    def roleNames(self) -> dict:
        return {
            self.FileNameRole: b"fileName",
            self.FilePathRole: b"filePath",
            self.StatusRole: b"status",
            self.ProgressRole: b"progress",
            self.ErrorMessageRole: b"errorMessage",
        }

    @Slot(list)
    def setFiles(self, files: list) -> None:
        """Set the file list from list of paths.

        Args:
            files: List of file path strings
        """
        self.beginResetModel()
        self._files = [
            {
                "fileName": Path(f).name,
                "filePath": f,
                "status": STATUS_PENDING,
                "progress": 0.0,
                "errorMessage": "",
            }
            for f in files
        ]
        self.endResetModel()

    @Slot(int, str)
    def setStatus(self, index: int, status: str) -> None:
        """Update the status of a file."""
        if self._valid_index(index):
            self._files[index]["status"] = status
            model_index = self.index(index, 0)
            self.dataChanged.emit(model_index, model_index, [self.StatusRole])

    @Slot(int, float)
    def setProgress(self, index: int, progress: float) -> None:
        """Update the progress of a file."""
        if self._valid_index(index):
            self._files[index]["progress"] = progress
            model_index = self.index(index, 0)
            self.dataChanged.emit(model_index, model_index, [self.ProgressRole])

    @Slot(int, str)
    def setError(self, index: int, message: str) -> None:
        """Set error status and message for a file."""
        if self._valid_index(index):
            self._files[index]["status"] = STATUS_ERROR
            self._files[index]["errorMessage"] = message
            model_index = self.index(index, 0)
            self.dataChanged.emit(
                model_index, model_index, [self.StatusRole, self.ErrorMessageRole]
            )

    @Slot()
    def clear(self) -> None:
        """Clear the file list."""
        self.beginResetModel()
        self._files = []
        self.endResetModel()

    def getFilePath(self, index: int) -> str:
        """Get the file path at the given index."""
        if self._valid_index(index):
            return self._files[index]["filePath"]
        return ""

    def getFiles(self) -> list[str]:
        """Get all file paths."""
        return [f["filePath"] for f in self._files]
