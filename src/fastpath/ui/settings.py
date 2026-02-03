"""QSettings wrapper for persisting user preferences."""

from __future__ import annotations

import json

from PySide6.QtCore import QObject, QSettings, Signal, Property


class Settings(QObject):
    """QSettings wrapper for persisting preprocessing preferences.

    Provides QML-bindable properties that automatically save to QSettings.
    Settings are persisted between application sessions.
    """

    defaultOutputDirChanged = Signal()
    lastTileSizeChanged = Signal()
    parallelWorkersChanged = Signal()
    vipsConcurrencyChanged = Signal()

    recentSlidesChanged = Signal()
    lastSlideDirUrlChanged = Signal()
    annotationsVisibleChanged = Signal()
    annotationToolChanged = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._settings = QSettings("FastPATH", "FastPATH")

    # Default output directory
    @Property(str, notify=defaultOutputDirChanged)
    def defaultOutputDir(self) -> str:
        return self._settings.value("preprocess/defaultOutputDir", "", str)

    @defaultOutputDir.setter
    def defaultOutputDir(self, value: str) -> None:
        if self.defaultOutputDir != value:
            self._settings.setValue("preprocess/defaultOutputDir", value)
            self.defaultOutputDirChanged.emit()

    # Last tile size (256, 512, 1024)
    @Property(int, notify=lastTileSizeChanged)
    def lastTileSize(self) -> int:
        return self._settings.value("preprocess/lastTileSize", 512, int)

    @lastTileSize.setter
    def lastTileSize(self, value: int) -> None:
        if self.lastTileSize != value:
            self._settings.setValue("preprocess/lastTileSize", value)
            self.lastTileSizeChanged.emit()

    # Parallel workers (1-8)
    @Property(int, notify=parallelWorkersChanged)
    def parallelWorkers(self) -> int:
        return self._settings.value("preprocess/parallelWorkers", 3, int)

    @parallelWorkers.setter
    def parallelWorkers(self, value: int) -> None:
        if self.parallelWorkers != value:
            self._settings.setValue("preprocess/parallelWorkers", value)
            self.parallelWorkersChanged.emit()

    # VIPS concurrency (0 = not benchmarked, use config default)
    @Property(int, notify=vipsConcurrencyChanged)
    def vipsConcurrency(self) -> int:
        return self._settings.value("preprocess/vipsConcurrency", 0, int)

    @vipsConcurrency.setter
    def vipsConcurrency(self, value: int) -> None:
        if self.vipsConcurrency != value:
            self._settings.setValue("preprocess/vipsConcurrency", value)
            self.vipsConcurrencyChanged.emit()

    # ------------------------------------------------------------------
    # Viewer settings
    # ------------------------------------------------------------------

    @Property(str, notify=lastSlideDirUrlChanged)
    def lastSlideDirUrl(self) -> str:
        return self._settings.value("viewer/lastSlideDirUrl", "", str)

    @lastSlideDirUrl.setter
    def lastSlideDirUrl(self, value: str) -> None:
        if self.lastSlideDirUrl != value:
            self._settings.setValue("viewer/lastSlideDirUrl", value)
            self.lastSlideDirUrlChanged.emit()

    @Property(bool, notify=annotationsVisibleChanged)
    def annotationsVisible(self) -> bool:
        return self._settings.value("viewer/annotationsVisible", True, bool)

    @annotationsVisible.setter
    def annotationsVisible(self, value: bool) -> None:
        if self.annotationsVisible != value:
            self._settings.setValue("viewer/annotationsVisible", value)
            self.annotationsVisibleChanged.emit()

    @Property(str, notify=annotationToolChanged)
    def annotationTool(self) -> str:
        return self._settings.value("viewer/annotationTool", "pan", str)

    @annotationTool.setter
    def annotationTool(self, value: str) -> None:
        if self.annotationTool != value:
            self._settings.setValue("viewer/annotationTool", value)
            self.annotationToolChanged.emit()

    def _load_recent_slide_paths(self) -> list[str]:
        raw = self._settings.value("viewer/recentSlidePaths", "[]", str)
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return []
        if not isinstance(parsed, list):
            return []
        return [str(p) for p in parsed if isinstance(p, str) and p]

    def _save_recent_slide_paths(self, paths: list[str]) -> None:
        self._settings.setValue("viewer/recentSlidePaths", json.dumps(paths))

    def get_recent_slide_paths(self) -> list[str]:
        """Return recent slide paths (most-recent first)."""
        return self._load_recent_slide_paths()

    def set_recent_slide_paths(self, paths: list[str]) -> None:
        """Persist recent slide paths (most-recent first)."""
        self._save_recent_slide_paths(paths)
        self.recentSlidesChanged.emit()
