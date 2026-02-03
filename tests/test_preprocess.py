"""Tests for the preprocessing pipeline."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fastpath.core.types import LevelInfo
from fastpath.preprocess.pyramid import VipsPyramidBuilder


class TestCalculateLevelsFromDimensions:
    """Tests for mathematical level computation from image dimensions."""

    @pytest.fixture
    def builder(self) -> VipsPyramidBuilder:
        return VipsPyramidBuilder.__new__(VipsPyramidBuilder)

    @pytest.mark.parametrize(
        "width, height, tile_size, expected",
        [
            # 2048x2048 / 512 → 3 levels, matches existing fixture
            (2048, 2048, 512, [
                LevelInfo(level=0, downsample=4, cols=1, rows=1),
                LevelInfo(level=1, downsample=2, cols=2, rows=2),
                LevelInfo(level=2, downsample=1, cols=4, rows=4),
            ]),
            # Image fits in a single tile → 1 level
            (512, 512, 512, [
                LevelInfo(level=0, downsample=1, cols=1, rows=1),
            ]),
            # Image smaller than tile size → 1 level
            (100, 100, 512, [
                LevelInfo(level=0, downsample=1, cols=1, rows=1),
            ]),
            # Non-power-of-2, non-square: halving gives 1025→513→257, 768→385→193
            (1025, 768, 512, [
                LevelInfo(level=0, downsample=4, cols=1, rows=1),
                LevelInfo(level=1, downsample=2, cols=2, rows=1),
                LevelInfo(level=2, downsample=1, cols=3, rows=2),
            ]),
        ],
        ids=["2048x2048", "single-tile", "smaller-than-tile", "non-square"],
    )
    def test_levels(
        self,
        builder: VipsPyramidBuilder,
        width: int,
        height: int,
        tile_size: int,
        expected: list[LevelInfo],
    ) -> None:
        result = builder._calculate_levels_from_dimensions(width, height, tile_size)
        assert result == expected

    def test_level_0_is_lowest_resolution(self, builder: VipsPyramidBuilder) -> None:
        """Level 0 should always have the highest downsample factor."""
        levels = builder._calculate_levels_from_dimensions(4096, 4096, 512)
        assert levels[0].level == 0
        assert levels[0].downsample == max(l.downsample for l in levels)

    def test_last_level_is_full_resolution(self, builder: VipsPyramidBuilder) -> None:
        """Last level should always have downsample=1."""
        levels = builder._calculate_levels_from_dimensions(4096, 4096, 512)
        assert levels[-1].downsample == 1


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
