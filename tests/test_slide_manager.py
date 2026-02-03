"""Tests for SlideManager."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fastpath.core.slide import SlideManager


@pytest.fixture
def loaded_slide_manager(qapp, mock_fastpath_dir: Path):
    """SlideManager pre-loaded with mock .fastpath directory."""
    manager = SlideManager()
    manager.load(str(mock_fastpath_dir))
    return manager


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

    def test_close_slide(self, loaded_slide_manager):
        """Should properly close a loaded slide."""
        assert loaded_slide_manager.isLoaded

        loaded_slide_manager.close()
        assert not loaded_slide_manager.isLoaded
        assert loaded_slide_manager.width == 0
        assert loaded_slide_manager.numLevels == 0

    def test_get_level_for_scale(self, loaded_slide_manager):
        """Should return appropriate level for different scales."""
        # Full resolution → level 2 (ds=1)
        assert loaded_slide_manager.getLevelForScale(1.0) == 2

        # Half resolution → level 1 (ds=2)
        assert loaded_slide_manager.getLevelForScale(0.5) == 1

        # Quarter resolution → level 0 (ds=4)
        assert loaded_slide_manager.getLevelForScale(0.25) == 0

        # Very small scale → level 0 (lowest resolution)
        assert loaded_slide_manager.getLevelForScale(0.1) == 0

    def test_get_visible_tiles(self, loaded_slide_manager):
        """Should return correct visible tiles for viewport."""
        # Full viewport at small scale should show few tiles
        tiles = loaded_slide_manager.getVisibleTiles(0, 0, 2048, 2048, 0.1)
        assert len(tiles) > 0

        # Small viewport should show fewer tiles
        tiles_small = loaded_slide_manager.getVisibleTiles(0, 0, 512, 512, 1.0)
        assert len(tiles_small) <= 4  # At most 2x2 tiles

    def test_get_tile_position(self, loaded_slide_manager):
        """Should return correct tile position in slide coordinates."""
        # Level 0 (ds=4): each tile covers 512*4=2048 pixels
        pos = loaded_slide_manager.getTilePosition(0, 0, 0)
        assert pos == [0, 0, 2048, 2048]

        # Level 2 (ds=1): each tile covers 512 pixels
        pos = loaded_slide_manager.getTilePosition(2, 0, 0)
        assert pos == [0, 0, 512, 512]

        # Level 2, second column
        pos = loaded_slide_manager.getTilePosition(2, 1, 0)
        assert pos == [512, 0, 512, 512]

        # Level 1 (ds=2): each tile covers 1024 pixels
        pos = loaded_slide_manager.getTilePosition(1, 0, 0)
        assert pos == [0, 0, 1024, 1024]

    def test_get_thumbnail_path(self, loaded_slide_manager):
        """Should return thumbnail path when loaded."""
        path = loaded_slide_manager.getThumbnailPath()
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

    @pytest.mark.parametrize("level, expected_ds, expected_cols, expected_rows", [
        (0, 4, 1, 1),
        (1, 2, 2, 2),
        (2, 1, 4, 4),
    ])
    def test_get_level_info(self, loaded_slide_manager, level, expected_ds, expected_cols, expected_rows):
        """Should return correct level info."""
        info = loaded_slide_manager.getLevelInfo(level)
        assert info[0] == expected_ds
        assert info[1] == expected_cols
        assert info[2] == expected_rows

    def test_get_level_info_invalid(self, loaded_slide_manager):
        """Should return zeros for invalid level."""
        info = loaded_slide_manager.getLevelInfo(99)
        assert info == [1, 0, 0]
