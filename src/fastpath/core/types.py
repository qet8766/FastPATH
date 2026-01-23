"""Shared type definitions for FastPATH core module."""

from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple


class TileCoord(NamedTuple):
    """Coordinate of a tile in the pyramid.

    Attributes:
        level: Pyramid level (0 = highest resolution)
        col: Column index (0-based)
        row: Row index (0-based)
    """

    level: int
    col: int
    row: int


@dataclass
class LevelInfo:
    """Information about a pyramid level.

    Attributes:
        level: Level index (0 = highest resolution)
        downsample: Downsample factor relative to level 0 (1, 2, 4, 8, ...)
        cols: Number of tile columns at this level
        rows: Number of tile rows at this level
    """

    level: int
    downsample: int
    cols: int
    rows: int
