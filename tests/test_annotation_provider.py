"""Tests for the AnnotationTileImageProvider."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QSize
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from fastpath.core.annotations import AnnotationManager
from fastpath.ui.providers import AnnotationTileImageProvider


@pytest.fixture(scope="session")
def qapp():
    """Create a Qt application for testing."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture
def mock_slide_manager():
    """Mock SlideManager with standard test values."""
    sm = MagicMock()
    sm.tileSize = 512
    sm.isLoaded = True
    # getLevelInfo returns [downsample, cols, rows]
    sm.getLevelInfo.return_value = [1, 4, 4]
    return sm


@pytest.fixture
def annotation_manager(qapp):
    """Fresh AnnotationManager for each test."""
    return AnnotationManager()


@pytest.fixture
def provider(annotation_manager, mock_slide_manager):
    """AnnotationTileImageProvider with test dependencies."""
    return AnnotationTileImageProvider(annotation_manager, mock_slide_manager)


class TestAnnotationTileImageProvider:
    """Tests for AnnotationTileImageProvider."""

    def test_provider_returns_transparent_when_empty(self, provider):
        """Provider should return a transparent RGBA image when no annotations exist."""
        size = QSize()
        result = provider.requestImage("0/0_0?g=0", size, QSize())

        assert not result.isNull()
        assert result.width() == 512
        assert result.height() == 512
        assert result.format() == QImage.Format.Format_RGBA8888

    def test_provider_renders_polygon(self, provider, annotation_manager):
        """Provider should render non-transparent pixels for an annotation in the tile."""
        # Add a rectangle annotation at tile (0,0) level 0 (downsample=1)
        # Tile covers slide coords (0,0) to (512,512)
        annotation_manager.addAnnotation(
            "rectangle", [[100, 100], [400, 400]], "Test", "#ff0000"
        )

        size = QSize()
        result = provider.requestImage("0/0_0?g=1", size, QSize())

        assert not result.isNull()
        assert result.width() == 512
        assert result.height() == 512

        # Check that the tile has some non-transparent pixels
        has_content = False
        for y in range(100, 400, 50):
            for x in range(100, 400, 50):
                pixel = result.pixelColor(x, y)
                if pixel.alpha() > 0:
                    has_content = True
                    break
            if has_content:
                break
        assert has_content, "Annotation tile should have non-transparent pixels where annotation exists"

    def test_provider_coord_transform(self, provider, annotation_manager, mock_slide_manager):
        """Annotation at known slide coords should render in the correct tile."""
        # Set level info for level 1 with downsample=2
        mock_slide_manager.getLevelInfo.return_value = [2, 2, 2]

        # Annotation at slide coords (1024+100, 1024+100) to (1024+400, 1024+400)
        # At downsample=2, tile_size=512: tile (1,1) covers slide coords (1024,1024)-(2048,2048)
        annotation_manager.addAnnotation(
            "rectangle", [[1124, 1124], [1424, 1424]], "Offset", "#00ff00"
        )

        # Tile (1,1) at level 1 should have content
        size = QSize()
        result = provider.requestImage("1/1_1?g=1", size, QSize())
        assert not result.isNull()

        # Check for non-transparent pixels in the expected local region
        # Local coords: (1124-1024)/2=50, (1424-1024)/2=200
        has_content = False
        for y in range(50, 200, 25):
            for x in range(50, 200, 25):
                pixel = result.pixelColor(x, y)
                if pixel.alpha() > 0:
                    has_content = True
                    break
            if has_content:
                break
        assert has_content, "Annotation should render at transformed local coordinates"

        # Tile (0,0) at level 1 should be transparent (annotation is not in this tile)
        result_empty = provider.requestImage("1/0_0?g=1", size, QSize())
        all_transparent = True
        # Sample a grid of pixels
        for y in range(0, 512, 64):
            for x in range(0, 512, 64):
                if result_empty.pixelColor(x, y).alpha() > 0:
                    all_transparent = False
                    break
            if not all_transparent:
                break
        assert all_transparent, "Tile without annotations should be fully transparent"

    def test_provider_cache_hit(self, provider, annotation_manager):
        """Second request with same generation should return cached result."""
        annotation_manager.addAnnotation(
            "rectangle", [[10, 10], [100, 100]], "Cache", "#0000ff"
        )

        size = QSize()
        result1 = provider.requestImage("0/0_0?g=1", size, QSize())
        result2 = provider.requestImage("0/0_0?g=1", size, QSize())

        # Both should be valid
        assert not result1.isNull()
        assert not result2.isNull()
        # Cache key is (level, col, row, generation) — same key returns same object
        assert result1 is result2

    def test_provider_generation_invalidates_cache(self, provider, annotation_manager):
        """Different generation should produce a new cache entry."""
        # Add an annotation so tiles have content (not the shared transparent singleton)
        annotation_manager.addAnnotation(
            "rectangle", [[10, 10], [100, 100]], "Gen", "#ff0000"
        )

        size = QSize()
        result_g0 = provider.requestImage("0/0_0?g=0", size, QSize())
        result_g1 = provider.requestImage("0/0_0?g=1", size, QSize())

        # Different generation keys should not return the same cached object
        assert result_g0 is not result_g1
        # Both should still be valid images
        assert not result_g0.isNull()
        assert not result_g1.isNull()

    def test_provider_handles_point_annotation(self, provider, annotation_manager):
        """Point annotations should render as circles."""
        annotation_manager.addAnnotation(
            "point", [[256, 256]], "Center", "#ff00ff"
        )

        size = QSize()
        result = provider.requestImage("0/0_0?g=1", size, QSize())
        assert not result.isNull()

        # Check for non-transparent pixels near the point center
        pixel = result.pixelColor(256, 256)
        assert pixel.alpha() > 0, "Point annotation should have visible pixels at center"

    def test_provider_handles_polygon_annotation(self, provider, annotation_manager):
        """Polygon annotations should render as filled shapes."""
        annotation_manager.addAnnotation(
            "polygon",
            [[100, 100], [400, 100], [400, 400], [100, 400]],
            "Square", "#00ff00"
        )

        size = QSize()
        result = provider.requestImage("0/0_0?g=1", size, QSize())
        assert not result.isNull()

        # Check center of polygon
        pixel = result.pixelColor(250, 250)
        assert pixel.alpha() > 0, "Polygon center should have visible pixels"

    def test_provider_slide_not_loaded(self, annotation_manager):
        """Provider should return transparent tile when slide is not loaded."""
        sm = MagicMock()
        sm.tileSize = 512
        sm.isLoaded = False
        p = AnnotationTileImageProvider(annotation_manager, sm)

        size = QSize()
        result = p.requestImage("0/0_0?g=0", size, QSize())
        assert not result.isNull()
        # Should be transparent
        assert result.pixelColor(0, 0).alpha() == 0
