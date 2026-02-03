"""Project management for FastPATH sessions."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Signal, Slot, Property

from fastpath.core.paths import atomic_json_save

logger = logging.getLogger(__name__)


@dataclass
class ProjectData:
    """Data structure for a FastPATH project."""

    version: str = "1.0"
    slide_path: str = ""
    annotations_file: str = ""
    view_state: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    modified_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "slide_path": self.slide_path,
            "annotations_file": self.annotations_file,
            "view_state": self.view_state,
            "created_at": self.created_at,
            "modified_at": self.modified_at,
            "metadata": self.metadata,
        }

    _KNOWN_VERSIONS = {"1.0"}

    @classmethod
    def from_dict(cls, data: dict) -> ProjectData:
        version = data.get("version", "1.0")
        if version not in cls._KNOWN_VERSIONS:
            logger.warning("Unrecognized project version %r, loading anyway", version)
        return cls(
            version=version,
            slide_path=data.get("slide_path", ""),
            annotations_file=data.get("annotations_file", ""),
            view_state=data.get("view_state", {}),
            created_at=data.get("created_at", ""),
            modified_at=data.get("modified_at", ""),
            metadata=data.get("metadata", {}),
        )


class ProjectManager(QObject):
    """Manages FastPATH project files (.fpproj).

    Projects store:
    - Reference to the .fastpath slide
    - Current view state (position, zoom)
    - Annotations
    - User metadata
    """

    projectLoaded = Signal()
    projectSaved = Signal()
    projectClosed = Signal()
    dirtyChanged = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._project: ProjectData | None = None
        self._project_path: Path | None = None
        self._dirty = False

    @Property(bool, notify=dirtyChanged)
    def isDirty(self) -> bool:
        """Whether the project has unsaved changes."""
        return self._dirty

    @Property(bool, notify=projectLoaded)
    def isLoaded(self) -> bool:
        """Whether a project is currently loaded."""
        return self._project is not None

    @Property(str, notify=projectLoaded)
    def projectPath(self) -> str:
        """Path to the current project file."""
        return str(self._project_path) if self._project_path else ""

    @Property(str, notify=projectLoaded)
    def slidePath(self) -> str:
        """Path to the slide in the current project."""
        return self._project.slide_path if self._project else ""

    @Property(str, notify=projectLoaded)
    def annotationsFile(self) -> str:
        """Path to the annotations file in the current project."""
        return self._project.annotations_file if self._project else ""

    def _set_dirty(self, dirty: bool) -> None:
        if self._dirty != dirty:
            self._dirty = dirty
            self.dirtyChanged.emit()

    @Slot(str, str)
    def newProject(self, slide_path: str, annotations_path: str = "") -> None:
        """Create a new project for a slide.

        Args:
            slide_path: Path to the .fastpath directory
            annotations_path: Optional path to annotations file
        """
        now = datetime.now(timezone.utc).isoformat()
        self._project = ProjectData(
            slide_path=slide_path,
            annotations_file=annotations_path,
            created_at=now,
            modified_at=now,
        )
        self._project_path = None
        self._set_dirty(True)
        self.projectLoaded.emit()

    @Slot(str, result=bool)
    def loadProject(self, path: str) -> bool:
        """Load a project from a .fpproj file.

        Args:
            path: Path to the project file

        Returns:
            True if loaded successfully
        """
        path = Path(path)
        if not path.exists():
            logger.error("Project file not found: %s", path)
            return False

        try:
            with open(path) as f:
                data = json.load(f)

            self._project = ProjectData.from_dict(data)
            self._project_path = path
            self._set_dirty(False)
            self.projectLoaded.emit()
            return True

        except (json.JSONDecodeError, KeyError) as e:
            logger.error("Failed to parse project file %s: %s", path, e)
            return False

    @Slot(str, result=bool)
    def saveProject(self, path: str = "") -> bool:
        """Save the current project.

        Args:
            path: Path to save to (uses current path if empty)

        Returns:
            True if saved successfully
        """
        if not self._project:
            return False

        if path:
            self._project_path = Path(path)
        elif not self._project_path:
            return False

        # Update modified time
        self._project.modified_at = datetime.now(timezone.utc).isoformat()

        try:
            atomic_json_save(self._project_path, self._project.to_dict())

            self._set_dirty(False)
            self.projectSaved.emit()
            return True

        except OSError as e:
            logger.error("Failed to save project to %s: %s", self._project_path, e)
            return False

    @Slot()
    def closeProject(self) -> None:
        """Close the current project."""
        self._project = None
        self._project_path = None
        self._set_dirty(False)
        self.projectClosed.emit()

    @Slot(float, float, float)
    def updateViewState(self, x: float, y: float, scale: float) -> None:
        """Update the stored view state.

        Args:
            x: Viewport X position
            y: Viewport Y position
            scale: Current zoom scale
        """
        if not self._project:
            logger.debug("updateViewState called with no project loaded")
            return
        self._project.view_state = {
            "x": x,
            "y": y,
            "scale": scale,
        }
        self._set_dirty(True)

    @Slot(result="QVariant")
    def getViewState(self) -> dict | None:
        """Get the stored view state."""
        if self._project:
            return self._project.view_state
        return None

    @Slot(str, str)
    def setMetadata(self, key: str, value: str) -> None:
        """Set a metadata value."""
        if self._project:
            self._project.metadata[key] = value
            self._set_dirty(True)

    @Slot(str)
    def setSlidePath(self, path: str) -> None:
        """Update the slide path stored in the project."""
        if self._project:
            self._project.slide_path = path
            self._set_dirty(True)
            self.projectLoaded.emit()

    @Slot(str)
    def setAnnotationsFile(self, path: str) -> None:
        """Update the annotations file path stored in the project."""
        if self._project:
            self._project.annotations_file = path
            self._set_dirty(True)
            self.projectLoaded.emit()

    @Slot(str, result=str)
    def getMetadata(self, key: str) -> str:
        """Get a metadata value."""
        if self._project:
            return self._project.metadata.get(key, "")
        return ""
