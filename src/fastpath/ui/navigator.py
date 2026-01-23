"""Multi-slide navigation for FastPATH viewer."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot, Property


class SlideNavigator(QObject):
    """Manages navigation between multiple slides in a directory."""

    slideListChanged = Signal()
    currentIndexChanged = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._slides: list[Path] = []
        self._current_index: int = -1

    @Property(int, notify=currentIndexChanged)
    def currentIndex(self) -> int:
        return self._current_index

    @Property(int, notify=slideListChanged)
    def totalSlides(self) -> int:
        return len(self._slides)

    @Property(bool, notify=slideListChanged)
    def hasMultipleSlides(self) -> bool:
        return len(self._slides) > 1

    @Property(str, notify=currentIndexChanged)
    def currentSlideName(self) -> str:
        if 0 <= self._current_index < len(self._slides):
            return self._slides[self._current_index].stem
        return ""

    @Slot(str)
    def scanDirectory(self, path: str) -> None:
        """Scan for .fastpath directories in the same parent folder."""
        slide_path = Path(path).resolve()
        parent_dir = slide_path.parent

        fastpath_dirs = sorted(
            [d for d in parent_dir.iterdir() if d.is_dir() and d.suffix == ".fastpath"],
            key=lambda p: p.name.lower(),
        )

        self._slides = fastpath_dirs
        try:
            self._current_index = self._slides.index(slide_path)
        except ValueError:
            self._current_index = 0 if self._slides else -1

        self.slideListChanged.emit()
        self.currentIndexChanged.emit()

    @Slot(result=str)
    def nextSlide(self) -> str:
        # Bounds check in case _slides was modified by scanDirectory()
        if not self._slides:
            return ""
        # Clamp index to valid range before incrementing
        self._current_index = min(self._current_index, len(self._slides) - 1)
        if self._current_index < len(self._slides) - 1:
            self._current_index += 1
            self.currentIndexChanged.emit()
            return str(self._slides[self._current_index])
        return ""

    @Slot(result=str)
    def previousSlide(self) -> str:
        # Bounds check in case _slides was modified by scanDirectory()
        if not self._slides:
            return ""
        # Clamp index to valid range before decrementing
        self._current_index = min(self._current_index, len(self._slides) - 1)
        if self._current_index > 0:
            self._current_index -= 1
            self.currentIndexChanged.emit()
            return str(self._slides[self._current_index])
        return ""
