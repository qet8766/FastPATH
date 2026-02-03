"""Tests for the preprocessing pipeline."""

from __future__ import annotations

import json
import struct
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

    Tests verify the packed format structure where:
    - tiles.pack + tiles.idx contain the tile pyramid
    - Level 0 = lowest resolution (smallest)
    - Level N = highest resolution (largest)
    """

    _PACK_HEADER = struct.Struct("<8sII")
    _PACK_LEVEL = struct.Struct("<IIIQ")
    _PACK_ENTRY = struct.Struct("<QII")

    def _read_index(self, idx_path: Path):
        data = idx_path.read_bytes()
        magic, version, level_count = self._PACK_HEADER.unpack_from(data, 0)
        assert magic == b"FPTIDX1\0"
        assert version == 1
        entries_base = self._PACK_HEADER.size + level_count * self._PACK_LEVEL.size
        levels = {}
        for i in range(level_count):
            level, cols, rows, entry_offset = self._PACK_LEVEL.unpack_from(
                data, self._PACK_HEADER.size + i * self._PACK_LEVEL.size
            )
            levels[level] = (cols, rows, entry_offset)
        return data, entries_base, levels

    def test_mock_fastpath_structure(self, mock_fastpath_dir: Path):
        """Verify mock fastpath directory has correct pack structure."""
        assert mock_fastpath_dir.exists()
        assert (mock_fastpath_dir / "metadata.json").exists()
        assert (mock_fastpath_dir / "thumbnail.jpg").exists()
        assert (mock_fastpath_dir / "tiles.pack").exists()
        assert (mock_fastpath_dir / "tiles.idx").exists()
        assert (mock_fastpath_dir / "annotations" / "default.geojson").exists()

        # Check metadata has pack format marker
        with open(mock_fastpath_dir / "metadata.json") as f:
            metadata = json.load(f)
        assert metadata.get("tile_format") == "pack_v1"

    def test_highest_res_tiles_exist(self, mock_fastpath_dir: Path):
        """Level 2 (highest resolution) should have 4x4 tiles."""
        data, entries_base, levels = self._read_index(mock_fastpath_dir / "tiles.idx")
        cols, rows, entry_offset = levels[2]
        assert cols * rows == 16

        entry_start = entries_base + entry_offset
        entries = []
        for i in range(cols * rows):
            offset, length, _ = self._PACK_ENTRY.unpack_from(
                data, entry_start + i * self._PACK_ENTRY.size
            )
            entries.append((offset, length))
        assert all(length > 0 for _, length in entries)

    def test_pyramid_levels_increase(self, mock_fastpath_dir: Path):
        """Higher level numbers should have more tiles (larger resolution)."""
        _data, _entries_base, levels = self._read_index(mock_fastpath_dir / "tiles.idx")
        level0 = levels[0][0] * levels[0][1]
        level1 = levels[1][0] * levels[1][1]
        level2 = levels[2][0] * levels[2][1]

        # Higher level numbers have more tiles
        assert level2 > level1 > level0
        assert level0 >= 1
