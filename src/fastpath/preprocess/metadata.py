"""Metadata types and validation for .fastpath pyramid directories."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from fastpath.core.types import LevelInfo

logger = logging.getLogger(__name__)


class PyramidStatus(Enum):
    """Status of an existing pyramid directory."""

    NOT_EXISTS = "not_exists"  # No .fastpath directory
    COMPLETE = "complete"  # Valid and complete
    INCOMPLETE = "incomplete"  # Missing required files
    CORRUPTED = "corrupted"  # Invalid metadata or structure


def check_pyramid_status(pyramid_dir: Path) -> PyramidStatus:
    """Check the status of an existing pyramid directory.

    Supports both traditional format (levels/) and dzsave format (slide_files/).

    Args:
        pyramid_dir: Path to the .fastpath directory

    Returns:
        PyramidStatus indicating the state
    """
    if not pyramid_dir.exists():
        return PyramidStatus.NOT_EXISTS

    # Check required files
    metadata_path = pyramid_dir / "metadata.json"
    if not metadata_path.exists():
        return PyramidStatus.INCOMPLETE

    # Validate metadata
    try:
        with open(metadata_path) as f:
            metadata = json.load(f)

        # Check required fields
        required_fields = [
            "version", "source_file", "tile_size", "dimensions", "levels"
        ]
        for field in required_fields:
            if field not in metadata:
                return PyramidStatus.CORRUPTED

        # Determine tile format (dzsave or traditional)
        tile_format = metadata.get("tile_format", "traditional")

        if tile_format == "dzsave":
            # Check slide_files directory structure
            slide_files_dir = pyramid_dir / "tiles_files"
            if not slide_files_dir.exists():
                return PyramidStatus.INCOMPLETE

            # Verify at least one level directory has tiles
            level_dirs = [d for d in slide_files_dir.iterdir() if d.is_dir() and d.name.isdigit()]
            if not level_dirs:
                return PyramidStatus.INCOMPLETE

            for level_dir in level_dirs:
                tiles = list(level_dir.glob("*.jpg"))
                if tiles:
                    break
            else:
                return PyramidStatus.INCOMPLETE
        else:
            # Traditional format: Check levels directory structure
            levels_dir = pyramid_dir / "levels"
            if not levels_dir.exists():
                return PyramidStatus.INCOMPLETE

            # Verify each level directory exists and has tiles
            for level_info in metadata["levels"]:
                level_dir = levels_dir / str(level_info["level"])
                if not level_dir.exists():
                    return PyramidStatus.INCOMPLETE

                # Check if level has at least some tiles (not empty)
                tiles = list(level_dir.glob("*.jpg"))
                if not tiles:
                    return PyramidStatus.INCOMPLETE

        # Check thumbnail exists
        if not (pyramid_dir / "thumbnail.jpg").exists():
            return PyramidStatus.INCOMPLETE

        return PyramidStatus.COMPLETE

    except (json.JSONDecodeError, KeyError, TypeError):
        return PyramidStatus.CORRUPTED


@dataclass
class PyramidMetadata:
    """Metadata for a tile pyramid."""

    version: str
    source_file: str
    source_mpp: float
    target_mpp: float
    target_magnification: float
    tile_size: int
    dimensions: tuple[int, int]
    levels: list[LevelInfo]
    background_color: tuple[int, int, int]
    preprocessed_at: str
    tile_format: str = "dzsave"

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "source_file": self.source_file,
            "source_mpp": self.source_mpp,
            "target_mpp": self.target_mpp,
            "target_magnification": self.target_magnification,
            "tile_size": self.tile_size,
            "dimensions": list(self.dimensions),
            "levels": [
                {
                    "level": l.level,
                    "downsample": l.downsample,
                    "cols": l.cols,
                    "rows": l.rows,
                }
                for l in self.levels
            ],
            "background_color": list(self.background_color),
            "preprocessed_at": self.preprocessed_at,
            "tile_format": self.tile_format,
        }

    @classmethod
    def from_dict(cls, data: dict) -> PyramidMetadata:
        return cls(
            version=data["version"],
            source_file=data["source_file"],
            source_mpp=data["source_mpp"],
            target_mpp=data["target_mpp"],
            target_magnification=data["target_magnification"],
            tile_size=data["tile_size"],
            dimensions=tuple(data["dimensions"]),
            levels=[
                LevelInfo(
                    level=l["level"],
                    downsample=l["downsample"],
                    cols=l["cols"],
                    rows=l["rows"],
                )
                for l in data["levels"]
            ],
            background_color=tuple(data["background_color"]),
            preprocessed_at=data["preprocessed_at"],
            tile_format=data.get("tile_format", "traditional"),
        )
