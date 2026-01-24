"""SlideManager for reading preprocessed .fastpath tile pyramids."""

from __future__ import annotations

import json
import logging
import threading
from collections import OrderedDict
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot, Property
from PySide6.QtGui import QImage

from fastpath.config import PYTHON_TILE_CACHE_SIZE, DEFAULT_TILE_SIZE
from fastpath.core.types import TileCoord, LevelInfo

logger = logging.getLogger(__name__)

# Import backends first to set up DLL paths on Windows
from fastpath.preprocess.backends import VIPSBackend, is_vips_available

# Import pyvips after DLL setup
try:
    import pyvips
except (ImportError, OSError):
    pyvips = None


class SlideManager(QObject):
    """Manages access to a preprocessed .fastpath tile pyramid.

    Provides tile loading, level selection, and viewport calculations
    for the QML viewer.

    Supports both traditional (levels/) and dzsave (slide_files/) tile formats.
    """

    slideLoaded = Signal()
    slideClosed = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._fastpath_dir: Path | None = None
        self._metadata: dict | None = None
        self._levels: list[LevelInfo] = []
        # Use OrderedDict for LRU cache behavior
        self._tile_cache: OrderedDict[TileCoord, QImage] = OrderedDict()
        self._cache_size = PYTHON_TILE_CACHE_SIZE
        self._cache_lock = threading.Lock()  # Thread safety for cache access
        self._tile_format: str = "traditional"  # "traditional" or "dzsave"
        self._max_dz_level: int = 0  # For dzsave level mapping

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

            # Detect tile format and set up level mapping
            self._tile_format = self._metadata.get("tile_format", "traditional")
            if self._tile_format == "dzsave":
                # Find max dzsave level for level mapping
                slide_files = path / "tiles_files"
                if slide_files.exists():
                    level_dirs = [
                        d for d in slide_files.iterdir()
                        if d.is_dir() and d.name.isdigit()
                    ]
                    if level_dirs:
                        self._max_dz_level = max(int(d.name) for d in level_dirs)

            self._tile_cache.clear()
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
        self._tile_cache.clear()
        self._tile_format = "traditional"
        self._max_dz_level = 0
        self.slideClosed.emit()

    @Property(bool, notify=slideLoaded)
    def isLoaded(self) -> bool:
        """Whether a slide is currently loaded."""
        return self._fastpath_dir is not None

    @Property(int, notify=slideLoaded)
    def width(self) -> int:
        """Slide width at level 0 in pixels."""
        if not self._metadata:
            return 0
        return self._metadata["dimensions"][0]

    @Property(int, notify=slideLoaded)
    def height(self) -> int:
        """Slide height at level 0 in pixels."""
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
        """Microns per pixel at level 0."""
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

        Args:
            scale: View scale (1.0 = full resolution, 0.5 = half)

        Returns:
            Level index (0 = highest resolution)
        """
        if not self._levels:
            return 0

        target_downsample = 1.0 / scale

        # Find the highest resolution level (lowest downsample) where downsample <= target.
        # This ensures we never show blurrier tiles than needed.
        best_level = 0  # Default to highest resolution if none qualify

        for level_info in self._levels:
            if level_info.downsample <= target_downsample:
                # This level has enough resolution - pick the highest level number
                # among those that qualify (higher level = lower resolution within
                # acceptable range, which is more efficient)
                if level_info.level > best_level:
                    best_level = level_info.level

        return best_level

    @Slot(int, result="QVariantList")
    def getLevelInfo(self, level: int) -> list:
        """Get information about a pyramid level.

        Returns: [downsample, cols, rows]
        """
        if 0 <= level < len(self._levels):
            info = self._levels[level]
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
        level_info = self._levels[level]
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

    def _get_tile_path_internal(self, level: int, col: int, row: int) -> Path | None:
        """Get the file path for a tile (internal method).

        Handles both traditional (levels/) and dzsave (slide_files/) formats.

        Args:
            level: FastPATH pyramid level (0 = highest resolution)
            col: Column index
            row: Row index

        Returns:
            Path object if tile exists, None otherwise
        """
        if not self._fastpath_dir:
            return None

        if self._tile_format == "dzsave":
            # dzsave levels are inverted: 0 = lowest resolution, max = highest
            # FastPATH level 0 = highest resolution = dzsave max level
            dz_level = self._max_dz_level - level
            tile_path = self._fastpath_dir / "tiles_files" / str(dz_level) / f"{col}_{row}.jpg"
        else:
            # Traditional format: levels/N/col_row.jpg
            tile_path = self._fastpath_dir / "levels" / str(level) / f"{col}_{row}.jpg"

        if tile_path.exists():
            return tile_path
        return None

    @Slot(int, int, int, result=str)
    def getTilePath(self, level: int, col: int, row: int) -> str:
        """Get the file path for a tile.

        Args:
            level: Pyramid level (0 = highest resolution)
            col: Column index (0-based)
            row: Row index (0-based)

        Returns:
            File path string, or empty string if tile doesn't exist or coords invalid.
        """
        # Bounds validation
        if level < 0 or level >= len(self._levels):
            logger.debug("Invalid level %d (valid: 0-%d)", level, len(self._levels) - 1)
            return ""

        level_info = self._levels[level]
        if col < 0 or col >= level_info.cols:
            logger.debug("Invalid col %d for level %d (valid: 0-%d)", col, level, level_info.cols - 1)
            return ""
        if row < 0 or row >= level_info.rows:
            logger.debug("Invalid row %d for level %d (valid: 0-%d)", row, level, level_info.rows - 1)
            return ""

        tile_path = self._get_tile_path_internal(level, col, row)
        return str(tile_path) if tile_path else ""

    def getTile(self, level: int, col: int, row: int) -> QImage | None:
        """Get a tile as a QImage.

        Uses thread-safe LRU cache for performance.

        Args:
            level: Pyramid level
            col: Column index
            row: Row index

        Returns:
            QImage or None if tile doesn't exist
        """
        if not self._fastpath_dir:
            return None

        coord = TileCoord(level, col, row)

        # Thread-safe cache check
        with self._cache_lock:
            if coord in self._tile_cache:
                # Move to end to mark as recently used (LRU behavior)
                self._tile_cache.move_to_end(coord)
                return self._tile_cache[coord]

        # Load from disk using format-aware path resolution (outside lock - I/O can be slow)
        tile_path = self._get_tile_path_internal(level, col, row)
        if tile_path is None:
            return None

        # Load using pyvips and convert to QImage
        try:
            if is_vips_available():
                # Load with pyvips
                vips_img = pyvips.Image.new_from_file(str(tile_path), access="sequential")
                # Ensure RGB
                if vips_img.bands == 4:
                    vips_img = vips_img.extract_band(0, n=3)
                elif vips_img.bands == 1:
                    vips_img = vips_img.bandjoin([vips_img, vips_img])

                # Convert to bytes
                data = vips_img.write_to_memory()
                qimage = QImage(
                    data,
                    vips_img.width,
                    vips_img.height,
                    vips_img.width * 3,
                    QImage.Format.Format_RGB888,
                )
                # Make a copy since the data buffer goes out of scope
                qimage = qimage.copy()
            else:
                # Fallback: use QImage directly
                qimage = QImage(str(tile_path))
                if qimage.isNull():
                    return None
                qimage = qimage.convertToFormat(QImage.Format.Format_RGB888)

            # Thread-safe cache insertion with LRU eviction
            with self._cache_lock:
                # Check again in case another thread loaded it
                if coord not in self._tile_cache:
                    if len(self._tile_cache) >= self._cache_size:
                        # Remove least recently used (oldest = first item)
                        self._tile_cache.popitem(last=False)
                    self._tile_cache[coord] = qimage

            return qimage
        except FileNotFoundError:
            logger.debug("Tile not found: (%d, %d, %d) at %s", level, col, row, tile_path)
            return None
        except OSError as e:
            logger.warning("I/O error loading tile (%d, %d, %d) from %s: %s", level, col, row, tile_path, e)
            return None
        except Exception as e:
            logger.warning("Unexpected error loading tile (%d, %d, %d) from %s: %s", level, col, row, tile_path, e)
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
        if not self._levels or level < 0 or level >= len(self._levels):
            return [0, 0, 0, 0]

        level_info = self._levels[level]
        tile_size = self.tileSize * level_info.downsample

        x = col * tile_size
        y = row * tile_size

        # Clamp tile dimensions to slide boundaries for edge tiles
        actual_width = max(0, min(tile_size, self.width - x))
        actual_height = max(0, min(tile_size, self.height - y))

        return [x, y, actual_width, actual_height]
