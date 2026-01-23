"""Tests for the annotation system."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from fastpath.core.annotations import (
    Annotation,
    AnnotationManager,
    AnnotationType,
)


@pytest.fixture(scope="session")
def qapp():
    """Create a Qt application for testing."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


class TestAnnotation:
    """Tests for Annotation dataclass."""

    def test_create_point_annotation(self):
        """Should create a point annotation."""
        ann = Annotation(
            id="test_001",
            type=AnnotationType.POINT,
            coordinates=[(100.0, 200.0)],
            properties={"label": "Marker", "color": "#ff0000"},
        )

        assert ann.id == "test_001"
        assert ann.type == AnnotationType.POINT
        assert ann.coordinates == [(100.0, 200.0)]
        assert ann.label == "Marker"
        assert ann.color == "#ff0000"

    def test_create_polygon_annotation(self):
        """Should create a polygon annotation."""
        coords = [(0, 0), (100, 0), (100, 100), (0, 100)]
        ann = Annotation(
            id="test_002",
            type=AnnotationType.POLYGON,
            coordinates=coords,
        )

        assert ann.type == AnnotationType.POLYGON
        assert len(ann.coordinates) == 4

    def test_bounds_calculation(self):
        """Should calculate correct bounding box."""
        ann = Annotation(
            id="test",
            type=AnnotationType.POLYGON,
            coordinates=[(10, 20), (50, 20), (50, 80), (10, 80)],
        )

        bounds = ann.bounds()
        assert bounds == (10, 20, 50, 80)

    def test_bounds_empty_coordinates(self):
        """Should return zero bounds for empty coordinates."""
        ann = Annotation(id="test", type=AnnotationType.POINT, coordinates=[])
        bounds = ann.bounds()
        assert bounds == (0, 0, 0, 0)

    def test_to_geojson_point(self):
        """Should convert point to GeoJSON."""
        ann = Annotation(
            id="point_001",
            type=AnnotationType.POINT,
            coordinates=[(100, 200)],
            properties={"label": "Test"},
        )

        feature = ann.to_geojson_feature()
        assert feature["type"] == "Feature"
        assert feature["id"] == "point_001"
        assert feature["geometry"]["type"] == "Point"
        assert feature["geometry"]["coordinates"] == [100, 200]
        assert feature["properties"]["label"] == "Test"
        assert feature["properties"]["annotation_type"] == "point"

    def test_to_geojson_rectangle(self):
        """Should convert rectangle to GeoJSON polygon."""
        ann = Annotation(
            id="rect_001",
            type=AnnotationType.RECTANGLE,
            coordinates=[(10, 20), (50, 80)],
        )

        feature = ann.to_geojson_feature()
        assert feature["geometry"]["type"] == "Polygon"
        # Rectangle converted to 5-point polygon (closed)
        coords = feature["geometry"]["coordinates"][0]
        assert len(coords) == 5
        assert coords[0] == coords[-1]  # Closed

    def test_to_geojson_polygon(self):
        """Should convert polygon to GeoJSON."""
        ann = Annotation(
            id="poly_001",
            type=AnnotationType.POLYGON,
            coordinates=[(0, 0), (100, 0), (50, 100)],
        )

        feature = ann.to_geojson_feature()
        assert feature["geometry"]["type"] == "Polygon"
        coords = feature["geometry"]["coordinates"][0]
        assert coords[0] == coords[-1]  # Closed

    def test_from_geojson_point(self):
        """Should create annotation from GeoJSON point."""
        feature = {
            "type": "Feature",
            "id": "p1",
            "geometry": {"type": "Point", "coordinates": [150, 250]},
            "properties": {"annotation_type": "point", "label": "Marker"},
        }

        ann = Annotation.from_geojson_feature(feature)
        assert ann.id == "p1"
        assert ann.type == AnnotationType.POINT
        assert ann.coordinates == [(150, 250)]
        assert ann.label == "Marker"

    def test_from_geojson_polygon(self):
        """Should create annotation from GeoJSON polygon."""
        feature = {
            "type": "Feature",
            "id": "poly1",
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[0, 0], [100, 0], [100, 100], [0, 100], [0, 0]]],
            },
            "properties": {"annotation_type": "polygon"},
        }

        ann = Annotation.from_geojson_feature(feature)
        assert ann.type == AnnotationType.POLYGON
        assert len(ann.coordinates) == 4  # Closing point removed


class TestAnnotationManager:
    """Tests for AnnotationManager class."""

    def test_initial_state(self, qapp):
        """Manager should start empty."""
        manager = AnnotationManager()
        assert manager.count == 0
        assert not manager.isDirty

    def test_add_annotation(self, qapp):
        """Should add an annotation."""
        manager = AnnotationManager()
        ann_id = manager.addAnnotation("point", [[100, 200]], "Test", "#ff0000")

        assert ann_id.startswith("ann_")
        assert manager.count == 1
        assert manager.isDirty

    def test_add_multiple_annotations(self, qapp):
        """Should add multiple annotations with unique IDs."""
        manager = AnnotationManager()
        id1 = manager.addAnnotation("point", [[100, 200]])
        id2 = manager.addAnnotation("rectangle", [[0, 0], [100, 100]])
        id3 = manager.addAnnotation("polygon", [[0, 0], [50, 0], [25, 50]])

        assert id1 != id2 != id3
        assert manager.count == 3

    def test_remove_annotation(self, qapp):
        """Should remove an annotation."""
        manager = AnnotationManager()
        ann_id = manager.addAnnotation("point", [[100, 200]])
        assert manager.count == 1

        manager.removeAnnotation(ann_id)
        assert manager.count == 0

    def test_remove_nonexistent_annotation(self, qapp):
        """Should handle removing nonexistent annotation."""
        manager = AnnotationManager()
        manager.removeAnnotation("nonexistent")  # Should not raise

    def test_update_coordinates(self, qapp):
        """Should update annotation coordinates."""
        manager = AnnotationManager()
        ann_id = manager.addAnnotation("point", [[100, 200]])

        manager.updateCoordinates(ann_id, [[300, 400]])

        ann = manager.getAnnotation(ann_id)
        assert ann["coordinates"] == [[300, 400]]

    def test_update_properties(self, qapp):
        """Should update annotation properties."""
        manager = AnnotationManager()
        ann_id = manager.addAnnotation("point", [[100, 200]], "Old", "#000000")

        manager.updateProperties(ann_id, "New", "#ffffff")

        ann = manager.getAnnotation(ann_id)
        assert ann["label"] == "New"
        assert ann["color"] == "#ffffff"

    def test_query_viewport(self, qapp):
        """Should return annotations in viewport."""
        manager = AnnotationManager()

        # Add annotations in different locations
        manager.addAnnotation("point", [[50, 50]], "In")  # In viewport
        manager.addAnnotation("point", [[500, 500]], "Out")  # Outside

        # Query viewport 0,0 to 100,100
        results = manager.queryViewport(0, 0, 100, 100)
        assert len(results) == 1
        assert results[0]["label"] == "In"

    def test_query_viewport_polygon(self, qapp):
        """Should return polygons intersecting viewport."""
        manager = AnnotationManager()

        # Polygon partially in viewport
        manager.addAnnotation(
            "polygon",
            [[50, 50], [150, 50], [150, 150], [50, 150]],
            "Partial",
        )

        results = manager.queryViewport(0, 0, 100, 100)
        assert len(results) == 1

    def test_get_all_annotations(self, qapp):
        """Should return all annotations."""
        manager = AnnotationManager()
        manager.addAnnotation("point", [[100, 200]], "A")
        manager.addAnnotation("point", [[300, 400]], "B")

        all_anns = manager.getAllAnnotations()
        assert len(all_anns) == 2
        labels = {a["label"] for a in all_anns}
        assert labels == {"A", "B"}

    def test_get_annotation(self, qapp):
        """Should return specific annotation."""
        manager = AnnotationManager()
        ann_id = manager.addAnnotation("point", [[100, 200]], "Test")

        ann = manager.getAnnotation(ann_id)
        assert ann is not None
        assert ann["id"] == ann_id
        assert ann["label"] == "Test"

    def test_get_nonexistent_annotation(self, qapp):
        """Should return None for nonexistent annotation."""
        manager = AnnotationManager()
        ann = manager.getAnnotation("nonexistent")
        assert ann is None

    def test_clear(self, qapp):
        """Should clear all annotations."""
        manager = AnnotationManager()
        manager.addAnnotation("point", [[100, 200]])
        manager.addAnnotation("point", [[300, 400]])
        assert manager.count == 2

        manager.clear()
        assert manager.count == 0

    def test_save_and_load(self, qapp, temp_dir: Path):
        """Should save and load annotations."""
        manager = AnnotationManager()
        manager.addAnnotation("point", [[100, 200]], "Point1", "#ff0000")
        manager.addAnnotation(
            "polygon",
            [[0, 0], [100, 0], [100, 100], [0, 100]],
            "Poly1",
            "#00ff00",
        )

        # Save
        save_path = temp_dir / "annotations.geojson"
        manager.save(str(save_path))
        assert save_path.exists()
        assert not manager.isDirty

        # Load into new manager
        manager2 = AnnotationManager()
        manager2.load(str(save_path))

        assert manager2.count == 2
        all_anns = manager2.getAllAnnotations()
        labels = {a["label"] for a in all_anns}
        assert labels == {"Point1", "Poly1"}

    def test_signals_emitted(self, qapp):
        """Should emit signals on changes."""
        manager = AnnotationManager()
        added_ids = []
        removed_ids = []
        modified_ids = []

        manager.annotationAdded.connect(added_ids.append)
        manager.annotationRemoved.connect(removed_ids.append)
        manager.annotationModified.connect(modified_ids.append)

        # Add
        ann_id = manager.addAnnotation("point", [[100, 200]])
        assert ann_id in added_ids

        # Modify
        manager.updateProperties(ann_id, "New", "#ffffff")
        assert ann_id in modified_ids

        # Remove
        manager.removeAnnotation(ann_id)
        assert ann_id in removed_ids


class TestAnnotationGeoJSONRoundTrip:
    """Tests for GeoJSON serialization round-trips."""

    def test_roundtrip_point(self):
        """Point annotation should survive round-trip."""
        original = Annotation(
            id="p1",
            type=AnnotationType.POINT,
            coordinates=[(123.5, 456.7)],
            properties={"label": "Test", "color": "#abcdef"},
        )

        feature = original.to_geojson_feature()
        restored = Annotation.from_geojson_feature(feature)

        assert restored.id == original.id
        assert restored.type == original.type
        assert restored.coordinates[0][0] == pytest.approx(original.coordinates[0][0])
        assert restored.coordinates[0][1] == pytest.approx(original.coordinates[0][1])
        assert restored.label == original.label
        assert restored.color == original.color

    def test_roundtrip_polygon(self):
        """Polygon annotation should survive round-trip."""
        original = Annotation(
            id="poly1",
            type=AnnotationType.POLYGON,
            coordinates=[(0, 0), (100, 0), (100, 100), (50, 150), (0, 100)],
            properties={"label": "Region", "color": "#123456"},
        )

        feature = original.to_geojson_feature()
        restored = Annotation.from_geojson_feature(feature)

        assert restored.id == original.id
        assert restored.type == original.type
        assert len(restored.coordinates) == len(original.coordinates)
