"""Annotation management with spatial indexing."""

from __future__ import annotations

import json
import logging
import os
import threading
import tempfile
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, TypedDict

from PySide6.QtCore import QObject, Signal, Slot, Property
from rtree import index

from fastpath.core.paths import atomic_json_save, to_local_path

logger = logging.getLogger(__name__)


class AnnotationDict(TypedDict):
    """Dictionary representation of an annotation for QML."""

    id: str
    type: str
    coordinates: list[list[float]]
    label: str
    color: str
    notes: str
    bounds: list[float]
    group: str


class AnnotationType(str, Enum):
    """Types of annotations."""

    POINT = "point"
    RECTANGLE = "rectangle"
    POLYGON = "polygon"
    FREEHAND = "freehand"


@dataclass
class Annotation:
    """A single annotation on the slide.

    Coordinates are in slide pixel space (level 0).
    """

    id: str
    type: AnnotationType
    coordinates: list[tuple[float, float]]
    properties: dict[str, Any] = field(default_factory=dict)

    @property
    def label(self) -> str:
        return self.properties.get("label", "")

    @label.setter
    def label(self, value: str) -> None:
        self.properties["label"] = value

    @property
    def color(self) -> str:
        return self.properties.get("color", "#ff6b6b")

    @color.setter
    def color(self, value: str) -> None:
        self.properties["color"] = value

    @property
    def notes(self) -> str:
        return self.properties.get("notes", "")

    @notes.setter
    def notes(self, value: str) -> None:
        self.properties["notes"] = value

    @property
    def group(self) -> str:
        return self.properties.get("group", "default")

    @group.setter
    def group(self, value: str) -> None:
        self.properties["group"] = value

    def bounds(self) -> tuple[float, float, float, float]:
        """Get bounding box (minx, miny, maxx, maxy)."""
        if not self.coordinates:
            return (0.0, 0.0, 0.0, 0.0)

        xs = [c[0] for c in self.coordinates]
        ys = [c[1] for c in self.coordinates]
        return (min(xs), min(ys), max(xs), max(ys))

    def to_geojson_feature(self) -> dict:
        """Convert to GeoJSON Feature."""
        if self.type == AnnotationType.POINT:
            geometry = {
                "type": "Point",
                "coordinates": list(self.coordinates[0]) if self.coordinates else [0, 0],
            }
        elif self.type == AnnotationType.RECTANGLE:
            # Convert rectangle to polygon
            if len(self.coordinates) >= 2:
                x1, y1 = self.coordinates[0]
                x2, y2 = self.coordinates[1]
                geometry = {
                    "type": "Polygon",
                    "coordinates": [
                        [[x1, y1], [x2, y1], [x2, y2], [x1, y2], [x1, y1]]
                    ],
                }
            else:
                geometry = {"type": "Polygon", "coordinates": [[]]}
        else:
            # Polygon or freehand
            coords = [list(c) for c in self.coordinates]
            if coords and coords[0] != coords[-1]:
                coords.append(coords[0])  # Close polygon
            geometry = {
                "type": "Polygon",
                "coordinates": [coords],
            }

        return {
            "type": "Feature",
            "id": self.id,
            "geometry": geometry,
            "properties": {
                "annotation_type": self.type.value,
                **self.properties,
            },
        }

    @classmethod
    def from_geojson_feature(cls, feature: dict) -> Annotation:
        """Create from GeoJSON Feature."""
        ann_id = feature.get("id", str(uuid.uuid4()))
        geometry = feature.get("geometry", {})
        properties = feature.get("properties", {})

        ann_type_str = properties.pop("annotation_type", None)
        geom_type = geometry.get("type", "")

        if geom_type == "Point":
            ann_type = AnnotationType.POINT
            coords = [tuple(geometry.get("coordinates", [0, 0]))]
        elif geom_type == "Polygon":
            raw_coords = geometry.get("coordinates", [[]])[0]
            coords = [tuple(c) for c in raw_coords]
            # Remove closing point if present
            if len(coords) > 1 and coords[0] == coords[-1]:
                coords = coords[:-1]

            # Determine if rectangle or polygon
            if ann_type_str == "rectangle":
                ann_type = AnnotationType.RECTANGLE
                if len(coords) >= 4:
                    coords = [coords[0], coords[2]]  # Just store corners
            elif ann_type_str == "freehand":
                ann_type = AnnotationType.FREEHAND
            else:
                ann_type = AnnotationType.POLYGON
        else:
            ann_type = AnnotationType.POLYGON
            coords = []

        return cls(
            id=ann_id,
            type=ann_type,
            coordinates=coords,
            properties=properties,
        )


class AnnotationManager(QObject):
    """Manages annotations with spatial indexing for efficient viewport queries.

    Uses R-tree index for fast spatial lookups.
    """

    annotationsChanged = Signal()
    annotationAdded = Signal(str)  # annotation id
    annotationRemoved = Signal(str)  # annotation id
    annotationModified = Signal(str)  # annotation id
    annotationsBatchAdded = Signal(int)  # count of annotations added
    groupsChanged = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._annotations: dict[str, Annotation] = {}
        self._index = index.Index()
        self._id_counter = 0
        self._dirty = False
        # Thread safety for R-tree access (RLock for reentrant calls)
        self._index_lock = threading.RLock()
        # R-tree requires integer IDs for insert/delete. We use incrementing
        # integers rather than hashing string IDs to guarantee uniqueness
        # (hash collisions would silently corrupt the index).
        self._next_rtree_id = 0
        self._id_to_rtree: dict[str, int] = {}  # annotation_id -> rtree_id

    def _index_insert(self, ann_id: str, bounds: tuple) -> None:
        """Allocate an R-tree integer ID and insert into the spatial index."""
        rtree_id = self._next_rtree_id
        self._next_rtree_id += 1
        self._id_to_rtree[ann_id] = rtree_id
        self._index.insert(rtree_id, bounds, obj=ann_id)

    @Property(int, notify=annotationsChanged)
    def count(self) -> int:
        """Number of annotations."""
        return len(self._annotations)

    @Property(bool, notify=annotationsChanged)
    def isDirty(self) -> bool:
        """Whether annotations have unsaved changes."""
        return self._dirty

    def _generate_id(self) -> str:
        """Generate a unique annotation ID."""
        self._id_counter += 1
        return f"ann_{self._id_counter:06d}"

    @Slot(str, list, result=str)
    def addAnnotation(
        self,
        ann_type: str,
        coordinates: list,
        label: str = "",
        color: str = "#ff6b6b",
    ) -> str:
        """Add a new annotation.

        Args:
            ann_type: Type string (point, rectangle, polygon, freehand)
            coordinates: List of [x, y] coordinate pairs
            label: Optional label
            color: Optional color (hex string)

        Returns:
            The annotation ID
        """
        if not coordinates:
            logger.warning("Skipping annotation with empty coordinates (type=%s)", ann_type)
            return ""

        ann_id = self._generate_id()
        coords = [tuple(c) for c in coordinates]

        annotation = Annotation(
            id=ann_id,
            type=AnnotationType(ann_type),
            coordinates=coords,
            properties={"label": label, "color": color},
        )

        self._annotations[ann_id] = annotation
        bounds = annotation.bounds()

        with self._index_lock:
            self._index_insert(ann_id, bounds)

        self._dirty = True
        self.annotationAdded.emit(ann_id)
        self.annotationsChanged.emit()
        return ann_id

    @Slot(str)
    def removeAnnotation(self, ann_id: str) -> None:
        """Remove an annotation by ID."""
        if ann_id not in self._annotations:
            return

        annotation = self._annotations[ann_id]
        bounds = annotation.bounds()

        # Use thread-safe R-tree access
        with self._index_lock:
            rtree_id = self._id_to_rtree.pop(ann_id, None)
            if rtree_id is not None:
                self._index.delete(rtree_id, bounds)
            else:
                logger.warning("Missing R-tree ID for annotation %s during removal", ann_id)

        del self._annotations[ann_id]

        self._dirty = True
        self.annotationRemoved.emit(ann_id)
        self.annotationsChanged.emit()

    @Slot(str, list)
    def updateCoordinates(self, ann_id: str, coordinates: list) -> None:
        """Update annotation coordinates."""
        if ann_id not in self._annotations:
            return

        annotation = self._annotations[ann_id]

        # Use thread-safe R-tree access
        with self._index_lock:
            rtree_id = self._id_to_rtree.get(ann_id)
            if rtree_id is None:
                logger.warning("Missing R-tree ID for annotation %s during coordinate update", ann_id)
                return

            # Remove old index entry
            old_bounds = annotation.bounds()
            self._index.delete(rtree_id, old_bounds)

            # Update coordinates
            annotation.coordinates = [tuple(c) for c in coordinates]

            # Add new index entry with same rtree_id
            new_bounds = annotation.bounds()
            self._index.insert(rtree_id, new_bounds, obj=ann_id)

        self._dirty = True
        self.annotationModified.emit(ann_id)
        self.annotationsChanged.emit()

    @Slot(str, str, str)
    def updateProperties(self, ann_id: str, label: str, color: str) -> None:
        """Update annotation properties."""
        if ann_id not in self._annotations:
            return

        annotation = self._annotations[ann_id]
        annotation.label = label
        annotation.color = color

        self._dirty = True
        self.annotationModified.emit(ann_id)
        self.annotationsChanged.emit()

    @Slot(float, float, float, float, result="QVariantList")
    def queryViewport(
        self, x: float, y: float, width: float, height: float
    ) -> list:
        """Query annotations intersecting a viewport.

        All coordinates are in slide pixel space (level 0 resolution),
        matching the coordinate system used by annotations.

        Args:
            x: Viewport left edge in slide pixels
            y: Viewport top edge in slide pixels
            width: Viewport width in slide pixels
            height: Viewport height in slide pixels

        Returns:
            List of annotation data dicts with keys: id, type, coordinates,
            label, color, notes, bounds
        """
        bounds = (x, y, x + width, y + height)

        # Thread-safe R-tree query - collect IDs under lock, process outside
        with self._index_lock:
            hits = list(self._index.intersection(bounds, objects=True))

        # Process hits outside the lock
        result = []
        for hit in hits:
            ann_id = hit.object
            if ann_id in self._annotations:
                annotation = self._annotations[ann_id]
                result.append(self._annotation_to_dict(annotation))

        return result

    @Slot(result="QVariantList")
    def getAllAnnotations(self) -> list:
        """Get all annotations."""
        return [self._annotation_to_dict(a) for a in self._annotations.values()]

    @Slot(str, result="QVariant")
    def getAnnotation(self, ann_id: str) -> dict | None:
        """Get a single annotation by ID."""
        if ann_id in self._annotations:
            return self._annotation_to_dict(self._annotations[ann_id])
        return None

    def _annotation_to_dict(self, annotation: Annotation) -> AnnotationDict:
        """Convert annotation to dict for QML."""
        return AnnotationDict(
            id=annotation.id,
            type=annotation.type.value,
            coordinates=[list(c) for c in annotation.coordinates],
            label=annotation.label,
            color=annotation.color,
            notes=annotation.notes,
            bounds=list(annotation.bounds()),
            group=annotation.group,
        )

    @Slot(list, str, result="QVariantList")
    def addAnnotationsBatch(
        self,
        annotations: list[dict],
        group: str = "default",
    ) -> list[str]:
        """Add multiple annotations in a single batch.

        Args:
            annotations: List of dicts with keys: type, coordinates, label, color
            group: Group name for all annotations in this batch

        Returns:
            List of annotation IDs
        """
        ids: list[str] = []
        with self._index_lock:
            for ann_data in annotations:
                coords_raw = ann_data.get("coordinates", [])
                if not coords_raw:
                    continue

                ann_id = self._generate_id()
                coords = [tuple(c) for c in coords_raw]
                annotation = Annotation(
                    id=ann_id,
                    type=AnnotationType(ann_data.get("type", "polygon")),
                    coordinates=coords,
                    properties={
                        "label": ann_data.get("label", ""),
                        "color": ann_data.get("color", "#ff6b6b"),
                        "group": group,
                    },
                )

                self._annotations[ann_id] = annotation
                bounds = annotation.bounds()
                self._index_insert(ann_id, bounds)
                ids.append(ann_id)

        if ids:
            self._dirty = True
            self.annotationsBatchAdded.emit(len(ids))
            self.groupsChanged.emit()
            self.annotationsChanged.emit()

        return ids

    @Slot(list)
    def removeAnnotationsBatch(self, ann_ids: list[str]) -> None:
        """Remove multiple annotations in a single batch.

        Args:
            ann_ids: List of annotation IDs to remove
        """
        removed = 0
        with self._index_lock:
            for ann_id in ann_ids:
                if ann_id not in self._annotations:
                    continue
                annotation = self._annotations[ann_id]
                bounds = annotation.bounds()
                rtree_id = self._id_to_rtree.pop(ann_id, None)
                if rtree_id is not None:
                    self._index.delete(rtree_id, bounds)
                del self._annotations[ann_id]
                removed += 1

        if removed:
            self._dirty = True
            self.groupsChanged.emit()
            self.annotationsChanged.emit()

    @Slot(str, result=int)
    def removeAnnotationsByGroup(self, group: str) -> int:
        """Remove all annotations in a group.

        Args:
            group: Group name

        Returns:
            Number of annotations removed
        """
        ids_to_remove = [
            ann_id for ann_id, ann in self._annotations.items()
            if ann.group == group
        ]
        self.removeAnnotationsBatch(ids_to_remove)
        return len(ids_to_remove)

    @Slot(str, result="QVariantList")
    def getAnnotationsByGroup(self, group: str) -> list:
        """Get all annotations in a group.

        Args:
            group: Group name

        Returns:
            List of annotation dicts
        """
        return [
            self._annotation_to_dict(ann)
            for ann in self._annotations.values()
            if ann.group == group
        ]

    @Slot(result="QVariantList")
    def getGroups(self) -> list[str]:
        """Get list of unique group names."""
        groups: set[str] = set()
        for ann in self._annotations.values():
            groups.add(ann.group)
        return sorted(groups)

    @Slot(str, result=int)
    def getGroupCount(self, group: str) -> int:
        """Get number of annotations in a group."""
        return sum(1 for ann in self._annotations.values() if ann.group == group)

    @Slot(str)
    def save(self, path: str) -> None:
        """Save annotations to GeoJSON file."""
        path = to_local_path(path)
        features = [a.to_geojson_feature() for a in self._annotations.values()]
        geojson = {"type": "FeatureCollection", "features": features}

        atomic_json_save(path, geojson)

        self._dirty = False
        self.annotationsChanged.emit()

    @Slot(str)
    def load(self, path: str) -> None:
        """Load annotations from GeoJSON file.

        Validates JSON and parses features before acquiring lock to minimize
        lock hold time. Only state updates are performed under the lock.
        """
        path = to_local_path(path)
        if not path.exists():
            logger.warning("Annotation file not found: %s", path)
            return

        # Parse JSON first - don't clear existing data if this fails
        try:
            with open(path) as f:
                geojson = json.load(f)
        except json.JSONDecodeError as e:
            logger.error("Invalid JSON in %s: %s", path, e)
            return  # Don't clear existing data on parse error

        if not isinstance(geojson, dict) or "features" not in geojson:
            logger.error("Missing 'features' in GeoJSON: %s", path)
            return  # Don't clear existing data on invalid format

        # Parse all features OUTSIDE the lock to minimize lock hold time
        parsed_annotations: list[Annotation] = []
        max_id_num = 0
        for feature in geojson.get("features", []):
            try:
                annotation = Annotation.from_geojson_feature(feature)
                parsed_annotations.append(annotation)
                # Track max ID for counter
                if annotation.id.startswith("ann_"):
                    try:
                        num = int(annotation.id[4:])
                        max_id_num = max(max_id_num, num)
                    except ValueError:
                        logger.debug("Non-numeric annotation ID suffix: %s", annotation.id)
            except Exception as e:
                logger.warning("Failed to parse annotation feature: %s", e)

        # Only clear after successful validation and parsing
        self.clear()

        # Batch update state under the lock (fast, no I/O)
        with self._index_lock:
            for annotation in parsed_annotations:
                self._annotations[annotation.id] = annotation
                self._index_insert(annotation.id, annotation.bounds())

            self._id_counter = max(self._id_counter, max_id_num)

        self._dirty = False
        self.annotationsChanged.emit()

    def _clear_all(self, dirty: bool) -> None:
        """Clear all annotations and reset the spatial index."""
        self._annotations.clear()
        with self._index_lock:
            self._index = index.Index()
            self._id_to_rtree.clear()
            self._next_rtree_id = 0
        self._dirty = dirty
        self.annotationsChanged.emit()

    @Slot()
    def clear(self) -> None:
        """Clear all annotations."""
        self._clear_all(dirty=True)

    @Slot()
    def reset(self) -> None:
        """Clear all annotations and mark state clean.

        Intended for slide switches where existing annotations should not
        carry over, without marking the new slide as having unsaved changes.
        """
        self._clear_all(dirty=False)
