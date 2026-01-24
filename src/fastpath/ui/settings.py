"""QSettings wrapper for persisting user preferences."""

from __future__ import annotations

from PySide6.QtCore import QObject, QSettings, Signal, Property


class Settings(QObject):
    """QSettings wrapper for persisting preprocessing preferences.

    Provides QML-bindable properties that automatically save to QSettings.
    Settings are persisted between application sessions.
    """

    defaultOutputDirChanged = Signal()
    lastTileSizeChanged = Signal()
    lastQualityChanged = Signal()
    lastMethodChanged = Signal()
    parallelWorkersChanged = Signal()

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

    # Last quality (70-100)
    @Property(int, notify=lastQualityChanged)
    def lastQuality(self) -> int:
        return self._settings.value("preprocess/lastQuality", 95, int)

    @lastQuality.setter
    def lastQuality(self, value: int) -> None:
        if self.lastQuality != value:
            self._settings.setValue("preprocess/lastQuality", value)
            self.lastQualityChanged.emit()

    # Last method (level1, level0_resized)
    @Property(str, notify=lastMethodChanged)
    def lastMethod(self) -> str:
        return self._settings.value("preprocess/lastMethod", "level1", str)

    @lastMethod.setter
    def lastMethod(self, value: str) -> None:
        if self.lastMethod != value:
            self._settings.setValue("preprocess/lastMethod", value)
            self.lastMethodChanged.emit()

    # Parallel workers (1-8)
    @Property(int, notify=parallelWorkersChanged)
    def parallelWorkers(self) -> int:
        return self._settings.value("preprocess/parallelWorkers", 3, int)

    @parallelWorkers.setter
    def parallelWorkers(self, value: int) -> None:
        if self.parallelWorkers != value:
            self._settings.setValue("preprocess/parallelWorkers", value)
            self.parallelWorkersChanged.emit()
