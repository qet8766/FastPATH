"""Tests for SlideManager."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

from fastpath.core.slide import SlideManager


@pytest.fixture(scope="session")
def qapp():
    """Create a Qt application for testing."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


class TestSlideManager:
    """Tests for SlideManager class."""

    def test_initial_state(self, qapp):
        """SlideManager should start with no slide loaded."""
        manager = SlideManager()
        assert not manager.isLoaded
        assert manager.width == 0
        assert manager.height == 0
        assert manager.numLevels == 0

    def test_load_valid_fastpath(self, qapp, mock_fastpath_dir: Path):
        """Should load a valid .fastpath directory."""
        manager = SlideManager()
        result = manager.load(str(mock_fastpath_dir))

        assert result is True
        assert manager.isLoaded
        assert manager.width == 2048
        assert manager.height == 2048
        assert manager.tileSize == 512
        assert manager.numLevels == 3
        assert manager.mpp == 0.5
        assert manager.magnification == 20
        assert manager.sourceFile == "test_slide.svs"

    def test_load_nonexistent_path(self, qapp, temp_dir: Path):
        """Should fail to load nonexistent path."""
        manager = SlideManager()
        result = manager.load(str(temp_dir / "nonexistent.fastpath"))

        assert result is False
        assert not manager.isLoaded

    def test_load_invalid_directory(self, qapp, temp_dir: Path):
        """Should fail to load directory without metadata.json."""
        invalid_dir = temp_dir / "invalid.fastpath"
        invalid_dir.mkdir()

        manager = SlideManager()
        result = manager.load(str(invalid_dir))

        assert result is False
        assert not manager.isLoaded

    def test_close_slide(self, qapp, mock_fastpath_dir: Path):
        """Should properly close a loaded slide."""
        manager = SlideManager()
        manager.load(str(mock_fastpath_dir))
        assert manager.isLoaded

        manager.close()
        assert not manager.isLoaded
        assert manager.width == 0
        assert manager.numLevels == 0

    def test_get_level_for_scale(self, qapp, mock_fastpath_dir: Path):
        """Should return appropriate level for different scales."""
        manager = SlideManager()
        manager.load(str(mock_fastpath_dir))

        # Full resolution
        assert manager.getLevelForScale(1.0) == 0

        # Half resolution
        assert manager.getLevelForScale(0.5) in [0, 1]

        # Quarter resolution
        assert manager.getLevelForScale(0.25) in [1, 2]

        # Very small scale
        assert manager.getLevelForScale(0.1) == 2

    def test_get_visible_tiles(self, qapp, mock_fastpath_dir: Path):
        """Should return correct visible tiles for viewport."""
        manager = SlideManager()
        manager.load(str(mock_fastpath_dir))

        # Full viewport at small scale should show few tiles
        tiles = manager.getVisibleTiles(0, 0, 2048, 2048, 0.1)
        assert len(tiles) > 0

        # Small viewport should show fewer tiles
        tiles_small = manager.getVisibleTiles(0, 0, 512, 512, 1.0)
        assert len(tiles_small) <= 4  # At most 2x2 tiles

    def test_get_tile_path(self, qapp, mock_fastpath_dir: Path):
        """Should return correct tile path."""
        manager = SlideManager()
        manager.load(str(mock_fastpath_dir))

        # Existing tile
        path = manager.getTilePath(0, 0, 0)
        assert path != ""
        assert Path(path).exists()

        # Non-existing tile
        path = manager.getTilePath(0, 100, 100)
        assert path == ""

    def test_get_tile_position(self, qapp, mock_fastpath_dir: Path):
        """Should return correct tile position in slide coordinates."""
        manager = SlideManager()
        manager.load(str(mock_fastpath_dir))

        # First tile at level 0
        pos = manager.getTilePosition(0, 0, 0)
        assert pos == [0, 0, 512, 512]

        # Second column
        pos = manager.getTilePosition(0, 1, 0)
        assert pos == [512, 0, 512, 512]

        # Level 1 tile (2x downsample)
        pos = manager.getTilePosition(1, 0, 0)
        assert pos == [0, 0, 1024, 1024]

    def test_get_thumbnail_path(self, qapp, mock_fastpath_dir: Path):
        """Should return thumbnail path when loaded."""
        manager = SlideManager()
        manager.load(str(mock_fastpath_dir))

        path = manager.getThumbnailPath()
        assert path != ""
        assert Path(path).exists()
        assert path.endswith("thumbnail.jpg")

    def test_signals_emitted(self, qapp, mock_fastpath_dir: Path):
        """Should emit signals on load/close."""
        manager = SlideManager()
        loaded_count = [0]
        closed_count = [0]

        def on_loaded():
            loaded_count[0] += 1

        def on_closed():
            closed_count[0] += 1

        manager.slideLoaded.connect(on_loaded)
        manager.slideClosed.connect(on_closed)

        manager.load(str(mock_fastpath_dir))
        assert loaded_count[0] == 1

        manager.close()
        assert closed_count[0] == 1


class TestLevelInfo:
    """Tests for level information."""

    def test_get_level_info(self, qapp, mock_fastpath_dir: Path):
        """Should return correct level info."""
        manager = SlideManager()
        manager.load(str(mock_fastpath_dir))

        # Level 0
        info = manager.getLevelInfo(0)
        assert info[0] == 1  # downsample
        assert info[1] == 4  # cols
        assert info[2] == 4  # rows

        # Level 1
        info = manager.getLevelInfo(1)
        assert info[0] == 2  # downsample
        assert info[1] == 2  # cols
        assert info[2] == 2  # rows

    def test_get_level_info_invalid(self, qapp, mock_fastpath_dir: Path):
        """Should return zeros for invalid level."""
        manager = SlideManager()
        manager.load(str(mock_fastpath_dir))

        info = manager.getLevelInfo(99)
        assert info == [1, 0, 0]
