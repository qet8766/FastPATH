"""Integration tests for the Rust tile scheduler."""

from __future__ import annotations

from pathlib import Path

import pytest

from fastpath_core import RustTileScheduler


@pytest.fixture
def loaded_scheduler(mock_fastpath_dir: Path):
    """RustTileScheduler pre-loaded with mock .fastpath directory."""
    scheduler = RustTileScheduler()
    scheduler.load(str(mock_fastpath_dir))
    return scheduler


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

    def test_get_metadata(self, loaded_scheduler):
        """Test getting slide metadata."""
        metadata = loaded_scheduler.get_metadata()
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

    @pytest.mark.parametrize("level, expected_ds, expected_cols, expected_rows", [
        (0, 4, 1, 1),
        (1, 2, 2, 2),
        (2, 1, 4, 4),
    ])
    def test_get_level_info(self, loaded_scheduler, level, expected_ds, expected_cols, expected_rows):
        """Test getting level information."""
        info = loaded_scheduler.get_level_info(level)
        assert info is not None
        downsample, cols, rows = info
        assert downsample == expected_ds
        assert cols == expected_cols
        assert rows == expected_rows

    def test_get_level_info_invalid(self, loaded_scheduler):
        """Test that invalid level returns None."""
        assert loaded_scheduler.get_level_info(99) is None

    def test_get_tile(self, loaded_scheduler):
        """Test getting a tile."""
        # Get a tile that exists
        tile = loaded_scheduler.get_tile(0, 0, 0)
        assert tile is not None
        data, width, height = tile
        assert isinstance(data, bytes)
        assert width > 0
        assert height > 0
        # RGB data: width * height * 3 bytes
        assert len(data) == width * height * 3

    def test_get_tile_not_exists(self, loaded_scheduler):
        """Test getting a tile that doesn't exist."""
        # Try to get a tile outside the grid
        tile = loaded_scheduler.get_tile(0, 99, 99)
        assert tile is None

    def test_get_tile_not_loaded(self):
        """Test getting a tile when no slide is loaded."""
        scheduler = RustTileScheduler()
        tile = scheduler.get_tile(0, 0, 0)
        assert tile is None

    def test_cache_stats(self, loaded_scheduler):
        """Test cache statistics."""
        # Initial stats
        stats = loaded_scheduler.cache_stats()
        assert stats["hits"] == 0
        assert stats["misses"] == 0

        # Load tiles from level 2 (highest resolution, 4x4 grid)
        loaded_scheduler.get_tile(2, 0, 0)  # Miss
        loaded_scheduler.get_tile(2, 0, 0)  # Hit
        loaded_scheduler.get_tile(2, 1, 0)  # Miss

        stats = loaded_scheduler.cache_stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 2
        assert stats["num_tiles"] == 2

    def test_update_viewport(self, loaded_scheduler):
        """Test viewport update for prefetching."""
        # Update viewport - should trigger prefetching
        loaded_scheduler.update_viewport(
            x=0.0,
            y=0.0,
            width=1024.0,
            height=1024.0,
            scale=1.0,
            velocity_x=100.0,
            velocity_y=0.0,
        )

        # Check that some tiles were prefetched
        stats = loaded_scheduler.cache_stats()
        assert stats["num_tiles"] > 0

    def test_update_viewport_without_velocity(self, loaded_scheduler):
        """Test viewport update without velocity parameters."""
        # Update viewport without velocity
        loaded_scheduler.update_viewport(
            x=0.0,
            y=0.0,
            width=512.0,
            height=512.0,
            scale=1.0,
        )

        # Should still work
        stats = loaded_scheduler.cache_stats()
        assert stats["num_tiles"] >= 0

    def test_clear_cache_on_new_load(self, mock_fastpath_dir: Path):
        """Test that cache is cleared when loading a new slide."""
        scheduler = RustTileScheduler()
        scheduler.load(str(mock_fastpath_dir))

        # Load tiles from level 2 (highest resolution, 4x4 grid)
        scheduler.get_tile(2, 0, 0)
        scheduler.get_tile(2, 1, 0)

        stats = scheduler.cache_stats()
        assert stats["num_tiles"] == 2

        # Close and reopen
        scheduler.close()
        scheduler.load(str(mock_fastpath_dir))

        # Cache should be cleared
        stats = scheduler.cache_stats()
        assert stats["num_tiles"] == 0

    def test_cache_stats_l2_keys(self):
        """Test that cache_stats() includes all L2 keys."""
        scheduler = RustTileScheduler()
        stats = scheduler.cache_stats()

        # L1 keys (backward-compatible)
        assert "hits" in stats
        assert "misses" in stats
        assert "hit_ratio" in stats
        assert "size_bytes" in stats
        assert "num_tiles" in stats

        # L2 keys
        assert "l2_hits" in stats
        assert "l2_misses" in stats
        assert "l2_hit_ratio" in stats
        assert "l2_size_bytes" in stats
        assert "l2_num_tiles" in stats

    def test_l2_populated_on_tile_load(self, loaded_scheduler):
        """Test that loading a tile populates the L2 compressed cache."""
        # L2 should be empty initially
        stats = loaded_scheduler.cache_stats()
        assert stats["l2_num_tiles"] == 0

        # Load a tile via get_tile (foreground path)
        tile = loaded_scheduler.get_tile(0, 0, 0)
        assert tile is not None

        # L2 should now have 1 tile
        stats = loaded_scheduler.cache_stats()
        assert stats["l2_num_tiles"] == 1

    def test_l2_persists_across_slide_switch(self, mock_fastpath_dir: Path):
        """Test that L2 cache survives close + reload (not cleared)."""
        scheduler = RustTileScheduler()
        scheduler.load(str(mock_fastpath_dir))

        # Load some tiles to populate L2
        scheduler.get_tile(0, 0, 0)
        scheduler.get_tile(2, 0, 0)
        scheduler.get_tile(2, 1, 0)

        stats = scheduler.cache_stats()
        l2_count_before = stats["l2_num_tiles"]
        assert l2_count_before >= 3

        # Close and reload — L1 is cleared, L2 is NOT
        scheduler.close()
        scheduler.load(str(mock_fastpath_dir))

        stats = scheduler.cache_stats()
        # L1 should be empty
        assert stats["num_tiles"] == 0
        # L2 should still have tiles
        assert stats["l2_num_tiles"] == l2_count_before


class TestRustSchedulerComparisonWithPython:
    """Tests comparing Rust scheduler output with Python SlideManager."""

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


