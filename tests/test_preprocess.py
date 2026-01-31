"""Tests for the preprocessing pipeline."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


class TestPreprocessIntegration:
    """Integration tests for the full preprocessing pipeline.

    Tests verify the dzsave format structure where:
    - tiles_files/ contains the tile pyramid
    - Level 0 = lowest resolution (smallest)
    - Level N = highest resolution (largest)
    """

    def test_mock_fastpath_structure(self, mock_fastpath_dir: Path):
        """Verify mock fastpath directory has correct dzsave structure."""
        assert mock_fastpath_dir.exists()
        assert (mock_fastpath_dir / "metadata.json").exists()
        assert (mock_fastpath_dir / "thumbnail.jpg").exists()
        # dzsave format uses tiles_files/ directory
        assert (mock_fastpath_dir / "tiles_files" / "0").exists()
        assert (mock_fastpath_dir / "tiles_files" / "1").exists()
        assert (mock_fastpath_dir / "tiles_files" / "2").exists()
        assert (mock_fastpath_dir / "annotations" / "default.geojson").exists()

        # Check metadata has dzsave format marker
        with open(mock_fastpath_dir / "metadata.json") as f:
            metadata = json.load(f)
        assert metadata.get("tile_format") == "dzsave"

    def test_highest_res_tiles_exist(self, mock_fastpath_dir: Path):
        """Level 2 (highest resolution) should have 4x4 tiles."""
        level2 = mock_fastpath_dir / "tiles_files" / "2"
        tiles = list(level2.glob("*.jpg"))
        assert len(tiles) == 16

    def test_pyramid_levels_increase(self, mock_fastpath_dir: Path):
        """Higher level numbers should have more tiles (larger resolution)."""
        level0 = len(list((mock_fastpath_dir / "tiles_files" / "0").glob("*.jpg")))
        level1 = len(list((mock_fastpath_dir / "tiles_files" / "1").glob("*.jpg")))
        level2 = len(list((mock_fastpath_dir / "tiles_files" / "2").glob("*.jpg")))

        # Higher level numbers have more tiles
        assert level2 > level1 > level0
        assert level0 >= 1
