"""SlideManager for reading preprocessed .fastpath tile pyramids."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot, Property

from fastpath.config import DEFAULT_TILE_SIZE
from fastpath.core.types import LevelInfo

logger = logging.getLogger(__name__)


class SlideManager(QObject):
    """Manages access to a preprocessed .fastpath tile pyramid.

    Provides tile loading, level selection, and viewport calculations
    for the QML viewer.

    """

    slideLoaded = Signal()
    slideClosed = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._fastpath_dir: Path | None = None
        self._metadata: dict | None = None
        self._levels: list[LevelInfo] = []

    @Slot(str)
    def load(self, path: str) -> bool:
        """Load a .fastpath directory.

        Args:
            path: Path to the .fastpath directory

        Returns:
            True if loaded successfully
        """
        path = Path(path)
        if not path.exists():
            logger.error("Slide path does not exist: %s", path)
            return False

        metadata_path = path / "metadata.json"
        if not metadata_path.exists():
            logger.error("Metadata file not found: %s", metadata_path)
            return False

        try:
            with open(metadata_path) as f:
                metadata = json.load(f)

            if metadata.get("tile_format") != "pack_v2":
                logger.error(
                    "Unsupported tile_format in metadata: %s",
                    metadata.get("tile_format"),
                )
                return False

            # Parse levels BEFORE setting state to ensure clean failure
            levels = [
                LevelInfo(
                    level=l["level"],
                    downsample=l["downsample"],
                    cols=l["cols"],
                    rows=l["rows"],
                )
                for l in metadata["levels"]
            ]

            # Only set state after successful parsing
            self._metadata = metadata
            self._fastpath_dir = path
            self._levels = levels

            self.slideLoaded.emit()
            return True
        except json.JSONDecodeError as e:
            logger.error("Invalid JSON in metadata file %s: %s", metadata_path, e)
            return False
        except KeyError as e:
            logger.error("Missing required key in metadata %s: %s", metadata_path, e)
            return False

    @Slot()
    def close(self) -> None:
        """Close the current slide."""
        self._fastpath_dir = None
        self._metadata = None
        self._levels = []
        self.slideClosed.emit()

    @Property(bool, notify=slideLoaded)
    def isLoaded(self) -> bool:
        """Whether a slide is currently loaded."""
        return self._fastpath_dir is not None

    @Property(int, notify=slideLoaded)
    def width(self) -> int:
        """Slide width at full resolution in pixels."""
        if not self._metadata:
            return 0
        return self._metadata["dimensions"][0]

    @Property(int, notify=slideLoaded)
    def height(self) -> int:
        """Slide height at full resolution in pixels."""
        if not self._metadata:
            return 0
        return self._metadata["dimensions"][1]

    @Property(int, notify=slideLoaded)
    def tileSize(self) -> int:
        """Tile size in pixels."""
        if not self._metadata:
            return DEFAULT_TILE_SIZE
        return self._metadata["tile_size"]

    @Property(int, notify=slideLoaded)
    def numLevels(self) -> int:
        """Number of pyramid levels."""
        return len(self._levels)

    @Property(float, notify=slideLoaded)
    def mpp(self) -> float:
        """Microns per pixel at full resolution."""
        if not self._metadata:
            return 0.5
        return self._metadata["target_mpp"]

    @Property(float, notify=slideLoaded)
    def magnification(self) -> float:
        """Target magnification (e.g., 20.0 for 20x)."""
        if not self._metadata:
            return 20.0
        return self._metadata["target_magnification"]

    @Property(str, notify=slideLoaded)
    def sourceFile(self) -> str:
        """Original source file name."""
        if not self._metadata:
            return ""
        return self._metadata.get("source_file", "")

    @Slot(float, result=int)
    def getLevelForScale(self, scale: float) -> int:
        """Get the best pyramid level for a given view scale.

        Biases toward higher resolution by picking the level with
        downsample <= target, ensuring crisp display (GPU downscaling
        looks better than upscaling).

        Convention-independent: works with any level numbering scheme
        by comparing downsample values rather than level indices.

        Args:
            scale: View scale (1.0 = full resolution, 0.5 = half)

        Returns:
            Level index for the best matching level
        """
        if not self._levels:
            return 0

        target_downsample = 1.0 / scale

        # Linear scan is fine here: pyramids have 5-10 levels at most,
        # so O(n) is faster than maintaining a sorted structure.
        best = None
        for level_info in self._levels:
            if level_info.downsample <= target_downsample:
                if best is None or level_info.downsample > best.downsample:
                    best = level_info

        if best is not None:
            return best.level

        # No level qualifies — return highest resolution (smallest downsample)
        return min(self._levels, key=lambda l: l.downsample).level

    @Slot(int, result="QVariantList")
    def getLevelInfo(self, level: int) -> list:
        """Get information about a pyramid level.

        Returns: [downsample, cols, rows]
        """
        for info in self._levels:
            if info.level == level:
                return [info.downsample, info.cols, info.rows]
        return [1, 0, 0]

    @Slot(float, float, float, float, float, result="QVariantList")
    def getVisibleTiles(
        self, x: float, y: float, width: float, height: float, scale: float
    ) -> list:
        """Get list of visible tile coordinates for a viewport.

        Args:
            x: Viewport left in slide coordinates
            y: Viewport top in slide coordinates
            width: Viewport width in slide coordinates
            height: Viewport height in slide coordinates
            scale: Current view scale (must be > 0)

        Returns:
            List of [level, col, row] for each visible tile
        """
        if not self._levels:
            return []

        if scale <= 0:
            logger.warning("Invalid scale value: %f (must be > 0)", scale)
            return []

        level = self.getLevelForScale(scale)
        level_info = self._get_level_info_internal(level)
        if level_info is None:
            return []
        downsample = level_info.downsample
        tile_size = self.tileSize

        # Calculate tile range in level coordinates
        level_tile_size = tile_size * downsample

        col_start = max(0, int(x / level_tile_size))
        col_end = min(level_info.cols, int((x + width) / level_tile_size) + 1)
        row_start = max(0, int(y / level_tile_size))
        row_end = min(level_info.rows, int((y + height) / level_tile_size) + 1)

        tiles = []
        for row in range(row_start, row_end):
            for col in range(col_start, col_end):
                tiles.append([level, col, row])

        return tiles

    def _get_level_info_internal(self, level: int) -> LevelInfo | None:
        """Get LevelInfo by level number (not index)."""
        for info in self._levels:
            if info.level == level:
                return info
        return None

    @Slot(result=str)
    def getThumbnailPath(self) -> str:
        """Get path to the thumbnail image."""
        if not self._fastpath_dir:
            return ""
        thumb_path = self._fastpath_dir / "thumbnail.jpg"
        if thumb_path.exists():
            return str(thumb_path)
        return ""

    @Slot(int, int, int, result="QVariantList")
    def getTilePosition(self, level: int, col: int, row: int) -> list:
        """Get the position of a tile in slide coordinates.

        Returns: [x, y, width, height]
        """
        level_info = self._get_level_info_internal(level)
        if not self._levels or level_info is None:
            return [0, 0, 0, 0]

        tile_size = self.tileSize * level_info.downsample

        x = col * tile_size
        y = row * tile_size

        # Clamp tile dimensions to slide boundaries for edge tiles
        actual_width = max(0, min(tile_size, self.width - x))
        actual_height = max(0, min(tile_size, self.height - y))

        return [x, y, actual_width, actual_height]
