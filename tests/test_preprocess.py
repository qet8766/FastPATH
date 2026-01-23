"""Tests for the preprocessing pipeline."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


class TestPreprocessIntegration:
    """Integration tests for the full preprocessing pipeline.

    Tests verify the dzsave format structure where:
    - tiles_files/ contains the tile pyramid
    - dzsave level 0 = smallest (FastPATH level 2)
    - dzsave level 2 = largest (FastPATH level 0)
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

    def test_level0_tiles_exist(self, mock_fastpath_dir: Path):
        """Largest dzsave level (level 2) should have 4x4 tiles (FastPATH level 0)."""
        # dzsave level 2 = FastPATH level 0 (full resolution)
        dz_level2 = mock_fastpath_dir / "tiles_files" / "2"
        tiles = list(dz_level2.glob("*.jpg"))
        assert len(tiles) == 16

    def test_pyramid_levels_decrease(self, mock_fastpath_dir: Path):
        """Higher dzsave levels should have more tiles (larger resolution)."""
        # dzsave: level 0 = smallest, level 2 = largest
        dz_level0 = len(list((mock_fastpath_dir / "tiles_files" / "0").glob("*.jpg")))
        dz_level1 = len(list((mock_fastpath_dir / "tiles_files" / "1").glob("*.jpg")))
        dz_level2 = len(list((mock_fastpath_dir / "tiles_files" / "2").glob("*.jpg")))

        # Higher level numbers have more tiles
        assert dz_level2 > dz_level1 > dz_level0
        assert dz_level0 >= 1
