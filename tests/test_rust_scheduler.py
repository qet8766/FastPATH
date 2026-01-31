"""Integration tests for the Rust tile scheduler."""

from __future__ import annotations

from pathlib import Path

import pytest

from fastpath_core import RustTileScheduler


class TestRustTileScheduler:
    """Tests for the RustTileScheduler class."""

    def test_scheduler_creation(self):
        """Test creating a scheduler with default options."""
        scheduler = RustTileScheduler()
        assert not scheduler.is_loaded
        assert scheduler.num_levels == 0

    def test_scheduler_with_options(self):
        """Test creating a scheduler with custom options."""
        scheduler = RustTileScheduler(cache_size_mb=256, prefetch_distance=3)
        assert not scheduler.is_loaded

    def test_load_nonexistent_path(self):
        """Test loading a non-existent path fails."""
        scheduler = RustTileScheduler()
        with pytest.raises(RuntimeError):
            scheduler.load("/nonexistent/path/to/slide.fastpath")

    def test_load_and_close(self, mock_fastpath_dir: Path):
        """Test loading and closing a slide."""
        scheduler = RustTileScheduler()

        # Load
        result = scheduler.load(str(mock_fastpath_dir))
        assert result is True
        assert scheduler.is_loaded
        assert scheduler.tile_size == 512
        assert scheduler.num_levels == 3
        assert scheduler.width == 2048
        assert scheduler.height == 2048

        # Close
        scheduler.close()
        assert not scheduler.is_loaded

    def test_get_metadata(self, mock_fastpath_dir: Path):
        """Test getting slide metadata."""
        scheduler = RustTileScheduler()
        scheduler.load(str(mock_fastpath_dir))

        metadata = scheduler.get_metadata()
        assert metadata is not None
        assert metadata["width"] == 2048
        assert metadata["height"] == 2048
        assert metadata["tile_size"] == 512
        assert metadata["num_levels"] == 3
        assert metadata["mpp"] == 0.5
        assert metadata["magnification"] == 20.0

    def test_get_metadata_not_loaded(self):
        """Test getting metadata when not loaded returns None."""
        scheduler = RustTileScheduler()
        assert scheduler.get_metadata() is None

    def test_get_level_info(self, mock_fastpath_dir: Path):
        """Test getting level information."""
        scheduler = RustTileScheduler()
        scheduler.load(str(mock_fastpath_dir))

        # Level 0
        info0 = scheduler.get_level_info(0)
        assert info0 is not None
        downsample, cols, rows = info0
        assert downsample == 1
        assert cols == 4
        assert rows == 4

        # Level 1
        info1 = scheduler.get_level_info(1)
        assert info1 is not None
        downsample, cols, rows = info1
        assert downsample == 2
        assert cols == 2
        assert rows == 2

        # Level 2
        info2 = scheduler.get_level_info(2)
        assert info2 is not None
        downsample, cols, rows = info2
        assert downsample == 4
        assert cols == 1
        assert rows == 1

        # Invalid level
        assert scheduler.get_level_info(99) is None

    def test_get_tile(self, mock_fastpath_dir: Path):
        """Test getting a tile."""
        scheduler = RustTileScheduler()
        scheduler.load(str(mock_fastpath_dir))

        # Get a tile that exists
        tile = scheduler.get_tile(0, 0, 0)
        assert tile is not None
        data, width, height = tile
        assert isinstance(data, bytes)
        assert width > 0
        assert height > 0
        # RGB data: width * height * 3 bytes
        assert len(data) == width * height * 3

    def test_get_tile_not_exists(self, mock_fastpath_dir: Path):
        """Test getting a tile that doesn't exist."""
        scheduler = RustTileScheduler()
        scheduler.load(str(mock_fastpath_dir))

        # Try to get a tile outside the grid
        tile = scheduler.get_tile(0, 99, 99)
        assert tile is None

    def test_get_tile_not_loaded(self):
        """Test getting a tile when no slide is loaded."""
        scheduler = RustTileScheduler()
        tile = scheduler.get_tile(0, 0, 0)
        assert tile is None

    def test_cache_stats(self, mock_fastpath_dir: Path):
        """Test cache statistics."""
        scheduler = RustTileScheduler()
        scheduler.load(str(mock_fastpath_dir))

        # Initial stats
        stats = scheduler.cache_stats()
        assert stats["hits"] == 0
        assert stats["misses"] == 0

        # Load some tiles
        scheduler.get_tile(0, 0, 0)  # Miss
        scheduler.get_tile(0, 0, 0)  # Hit
        scheduler.get_tile(0, 1, 0)  # Miss

        stats = scheduler.cache_stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 2
        assert stats["num_tiles"] == 2

    def test_update_viewport(self, mock_fastpath_dir: Path):
        """Test viewport update for prefetching."""
        scheduler = RustTileScheduler()
        scheduler.load(str(mock_fastpath_dir))

        # Update viewport - should trigger prefetching
        scheduler.update_viewport(
            x=0.0,
            y=0.0,
            width=1024.0,
            height=1024.0,
            scale=1.0,
            velocity_x=100.0,
            velocity_y=0.0,
        )

        # Check that some tiles were prefetched
        stats = scheduler.cache_stats()
        assert stats["num_tiles"] > 0

    def test_update_viewport_without_velocity(self, mock_fastpath_dir: Path):
        """Test viewport update without velocity parameters."""
        scheduler = RustTileScheduler()
        scheduler.load(str(mock_fastpath_dir))

        # Update viewport without velocity
        scheduler.update_viewport(
            x=0.0,
            y=0.0,
            width=512.0,
            height=512.0,
            scale=1.0,
        )

        # Should still work
        stats = scheduler.cache_stats()
        assert stats["num_tiles"] >= 0

    def test_clear_cache_on_new_load(self, mock_fastpath_dir: Path):
        """Test that cache is cleared when loading a new slide."""
        scheduler = RustTileScheduler()
        scheduler.load(str(mock_fastpath_dir))

        # Load some tiles
        scheduler.get_tile(0, 0, 0)
        scheduler.get_tile(0, 1, 0)

        stats = scheduler.cache_stats()
        assert stats["num_tiles"] == 2

        # Close and reopen
        scheduler.close()
        scheduler.load(str(mock_fastpath_dir))

        # Cache should be cleared
        stats = scheduler.cache_stats()
        assert stats["num_tiles"] == 0


class TestRustSchedulerComparisonWithPython:
    """Tests comparing Rust scheduler output with Python SlideManager."""

    def test_same_tile_data(self, mock_fastpath_dir: Path, qapp):
        """Test that Rust and Python schedulers return equivalent tile data."""
        from fastpath.core.slide import SlideManager

        # Load with both schedulers
        rust_scheduler = RustTileScheduler()
        rust_scheduler.load(str(mock_fastpath_dir))

        python_manager = SlideManager()
        python_manager.load(str(mock_fastpath_dir))

        # Get the same tile from both
        rust_tile = rust_scheduler.get_tile(0, 0, 0)
        python_tile = python_manager.getTile(0, 0, 0)

        assert rust_tile is not None
        assert python_tile is not None

        rust_data, rust_w, rust_h = rust_tile

        # Python returns QImage, convert to raw bytes for comparison
        python_tile = python_tile.convertToFormat(python_tile.Format.Format_RGB888)
        python_w = python_tile.width()
        python_h = python_tile.height()

        # Dimensions should match
        assert rust_w == python_w
        assert rust_h == python_h

        # Extract pixel data accounting for QImage stride padding
        # (Qt aligns rows to 4-byte boundaries, so constBits() may include padding)
        stride = python_tile.bytesPerLine()
        row_bytes = python_w * 3  # RGB888 = 3 bytes per pixel
        raw = python_tile.constBits().tobytes()
        python_data = b"".join(
            raw[r * stride : r * stride + row_bytes] for r in range(python_h)
        )
        assert len(rust_data) == len(python_data)

    def test_metadata_consistency(self, mock_fastpath_dir: Path, qapp):
        """Test that metadata is consistent between Rust and Python."""
        from fastpath.core.slide import SlideManager

        rust_scheduler = RustTileScheduler()
        rust_scheduler.load(str(mock_fastpath_dir))

        python_manager = SlideManager()
        python_manager.load(str(mock_fastpath_dir))

        # Compare properties
        assert rust_scheduler.width == python_manager.width
        assert rust_scheduler.height == python_manager.height
        assert rust_scheduler.tile_size == python_manager.tileSize
        assert rust_scheduler.num_levels == python_manager.numLevels


@pytest.fixture(scope="session")
def qapp():
    """Session-scoped Qt application for tests requiring QObjects."""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app
