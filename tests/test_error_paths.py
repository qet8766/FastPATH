"""Tests for error handling paths added during code review.

These tests verify that:
1. Corrupted files don't cause crashes or data loss
2. Thread safety is maintained under concurrent access
3. Error conditions are properly logged and handled
"""

from __future__ import annotations

import json
import threading
import random
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from fastpath.core.slide import SlideManager
from fastpath.core.annotations import AnnotationManager
from fastpath.core.project import ProjectManager


@pytest.fixture(scope="session")
def qapp():
    """Create a Qt application for testing."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


class TestSlideManagerErrors:
    """Tests for SlideManager error handling."""

    def test_load_malformed_json(self, qapp, temp_dir: Path):
        """Corrupted metadata.json should return False, not crash."""
        fastpath_dir = temp_dir / "test.fastpath"
        fastpath_dir.mkdir()
        (fastpath_dir / "metadata.json").write_text("{invalid json")

        manager = SlideManager()
        result = manager.load(str(fastpath_dir))

        assert result is False
        assert not manager.isLoaded

    def test_load_missing_keys_json(self, qapp, temp_dir: Path):
        """metadata.json with missing required keys should return False."""
        fastpath_dir = temp_dir / "test.fastpath"
        fastpath_dir.mkdir()
        # Missing 'levels' key
        (fastpath_dir / "metadata.json").write_text('{"dimensions": [100, 100]}')

        manager = SlideManager()
        result = manager.load(str(fastpath_dir))

        assert result is False
        assert not manager.isLoaded

    def test_get_tile_nonexistent_returns_none(self, qapp, mock_fastpath_dir: Path):
        """getTile for non-existent tile should return None, not crash."""
        manager = SlideManager()
        manager.load(str(mock_fastpath_dir))

        # Request a tile that doesn't exist
        tile = manager.getTile(0, 999, 999)
        assert tile is None


class TestAnnotationManagerErrors:
    """Tests for AnnotationManager error handling."""

    def test_load_corrupted_geojson(self, qapp, temp_dir: Path):
        """Corrupted JSON should not clear existing annotations."""
        manager = AnnotationManager()
        manager.addAnnotation("point", [[100, 100]], "Test")
        assert manager.count == 1

        bad_file = temp_dir / "bad.geojson"
        bad_file.write_text("{not valid json")
        manager.load(str(bad_file))

        # Original annotation should still be there
        assert manager.count == 1

    def test_load_missing_features_key(self, qapp, temp_dir: Path):
        """GeoJSON without 'features' key should not clear existing annotations."""
        manager = AnnotationManager()
        manager.addAnnotation("point", [[100, 100]], "Test")
        assert manager.count == 1

        bad_file = temp_dir / "bad.geojson"
        bad_file.write_text('{"type": "FeatureCollection"}')  # Missing 'features'
        manager.load(str(bad_file))

        # Original annotation should still be there
        assert manager.count == 1

    def test_load_nonexistent_file(self, qapp):
        """Loading nonexistent file should not crash or clear annotations."""
        manager = AnnotationManager()
        manager.addAnnotation("point", [[100, 100]], "Test")

        manager.load("/nonexistent/path.geojson")
        assert manager.count == 1


class TestProjectManagerErrors:
    """Tests for ProjectManager error handling."""

    def test_load_corrupted_project(self, qapp, temp_dir: Path):
        """Corrupted project file should return False, not crash."""
        bad_file = temp_dir / "bad.fpproj"
        bad_file.write_text("{invalid json")

        manager = ProjectManager()
        result = manager.loadProject(str(bad_file))

        assert result is False
        assert not manager.isLoaded

    def test_load_nonexistent_project(self, qapp):
        """Loading nonexistent project should return False."""
        manager = ProjectManager()
        result = manager.loadProject("/nonexistent/path.fpproj")

        assert result is False
        assert not manager.isLoaded


class TestThreadSafety:
    """Tests for thread safety of concurrent operations."""

    def test_tile_cache_concurrent_access(self, qapp, mock_fastpath_dir: Path):
        """Multiple threads accessing cache should not corrupt it."""
        manager = SlideManager()
        manager.load(str(mock_fastpath_dir))

        errors = []
        tiles_loaded = []

        def worker():
            try:
                for _ in range(50):
                    level = 0
                    col = random.randint(0, 3)
                    row = random.randint(0, 3)
                    tile = manager.getTile(level, col, row)
                    if tile is not None:
                        tiles_loaded.append((level, col, row))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Thread errors: {errors}"
        # Should have loaded some tiles successfully
        assert len(tiles_loaded) > 0

    def test_annotation_rtree_concurrent_access(self, qapp):
        """Multiple threads modifying annotations should not crash."""
        manager = AnnotationManager()
        errors = []
        operations = []

        def writer():
            try:
                for i in range(20):
                    ann_id = manager.addAnnotation(
                        "point",
                        [[random.randint(0, 1000), random.randint(0, 1000)]],
                        f"Test_{threading.current_thread().name}_{i}"
                    )
                    operations.append(("add", ann_id))
            except Exception as e:
                errors.append(("write", e))

        def reader():
            try:
                for _ in range(20):
                    x = random.randint(0, 800)
                    y = random.randint(0, 800)
                    results = manager.queryViewport(x, y, 200, 200)
                    operations.append(("query", len(results)))
            except Exception as e:
                errors.append(("read", e))

        threads = []
        for i in range(2):
            threads.append(threading.Thread(target=writer, name=f"writer_{i}"))
            threads.append(threading.Thread(target=reader, name=f"reader_{i}"))

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Thread errors: {errors}"
        # Should have completed operations
        assert len(operations) > 0


class TestLRUCache:
    """Tests for LRU cache behavior."""

    def test_lru_eviction_order(self, qapp, mock_fastpath_dir: Path):
        """Cache should evict least recently used tiles."""
        manager = SlideManager()
        manager._cache_size = 4  # Small cache for testing
        manager.load(str(mock_fastpath_dir))

        # Load tiles A, B, C, D
        manager.getTile(0, 0, 0)  # A
        manager.getTile(0, 1, 0)  # B
        manager.getTile(0, 2, 0)  # C
        manager.getTile(0, 3, 0)  # D

        # Access A again (should move to end, making B the oldest)
        manager.getTile(0, 0, 0)  # A accessed again

        # Load a new tile E - should evict B (oldest)
        manager.getTile(0, 0, 1)  # E

        # Check cache contents
        from fastpath.core.slide import TileCoord

        with manager._cache_lock:
            cache_keys = list(manager._tile_cache.keys())

        # B should have been evicted (coord 0,1,0)
        assert TileCoord(0, 1, 0) not in cache_keys
        # A should still be in cache
        assert TileCoord(0, 0, 0) in cache_keys


class TestRTreeIntegerIds:
    """Tests for R-tree using integer IDs instead of hash."""

    def test_many_annotations_no_collisions(self, qapp):
        """Adding many annotations should not cause ID collisions."""
        manager = AnnotationManager()

        # Add 1000 annotations
        ann_ids = []
        for i in range(1000):
            ann_id = manager.addAnnotation(
                "point",
                [[i * 10, i * 10]],
                f"Test_{i}"
            )
            ann_ids.append(ann_id)

        # All should be queryable
        assert manager.count == 1000

        # Query should return correct results
        results = manager.queryViewport(0, 0, 10000, 10000)
        assert len(results) == 1000

        # Remove all and verify
        for ann_id in ann_ids:
            manager.removeAnnotation(ann_id)

        assert manager.count == 0
