"""Shared type definitions for FastPATH core module."""

from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple


class TileCoord(NamedTuple):
    """Coordinate of a tile in the pyramid.

    Attributes:
        level: Pyramid level (0 = lowest resolution)
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
        level: Level index (0 = lowest resolution)
        downsample: Downsample factor relative to highest resolution (1 = full res)
        cols: Number of tile columns at this level
        rows: Number of tile rows at this level
    """

    level: int
    downsample: int
    cols: int
    rows: int
    mpp: float = 0.0
