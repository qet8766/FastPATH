"""Metadata types and validation for .fastpath pyramid directories."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from fastpath.core.types import LevelInfo

logger = logging.getLogger(__name__)


def pyramid_dir_for_slide(slide_path: Path, output_dir: Path) -> Path:
    """Construct the .fastpath directory path for a slide.

    Args:
        slide_path: Path to the source WSI file
        output_dir: Parent directory for the .fastpath folder

    Returns:
        Path like ``output_dir / "slide_name.fastpath"``
    """
    return output_dir / (slide_path.stem + ".fastpath")


class PyramidStatus(Enum):
    """Status of an existing pyramid directory."""

    NOT_EXISTS = "not_exists"  # No .fastpath directory
    COMPLETE = "complete"  # Valid and complete
    INCOMPLETE = "incomplete"  # Missing required files
    CORRUPTED = "corrupted"  # Invalid metadata or structure


def check_pyramid_status(pyramid_dir: Path) -> PyramidStatus:
    """Check the status of an existing pyramid directory.

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

        # Validate tile format
        if metadata.get("tile_format") != "pack_v2":
            return PyramidStatus.CORRUPTED

        # Check packed tile files
        tiles_dir = pyramid_dir / "tiles"
        if not tiles_dir.exists():
            return PyramidStatus.INCOMPLETE
        for level_info in metadata["levels"]:
            level = level_info["level"]
            if not (tiles_dir / f"level_{level}.pack").exists():
                return PyramidStatus.INCOMPLETE
            if not (tiles_dir / f"level_{level}.idx").exists():
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
    tile_format: str = "pack_v2"

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
            tile_format=data.get("tile_format", "pack_v2"),
        )
