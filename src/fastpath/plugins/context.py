"""SlideContext — read-only access to a .fastpath pyramid directory.

Plain Python class (not QObject). Does NOT import ``core/slide.py``.
Reads the pyramid metadata and tiles directly from the filesystem.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import numpy as np

from fastpath.core.types import LevelInfo
from fastpath.preprocess.backends import VIPSBackend, is_vips_available

from .types import RegionOfInterest

logger = logging.getLogger(__name__)

try:
    import pyvips
except (ImportError, OSError):
    pyvips = None

try:
    from PIL import Image as PILImage
except ImportError:
    PILImage = None


@dataclass
class TileInfo:
    """A single tile yielded by ``SlideContext.iter_tiles()``."""

    col: int
    row: int
    image: np.ndarray
    slide_bounds: tuple[float, float, float, float]  # (x, y, w, h) in slide coords


class SlideContext:
    """Read-only access to a preprocessed ``.fastpath`` pyramid.

    Provides tile I/O, coordinate helpers, and level iteration.
    Plugins use this instead of needing a WSI library.
    """

    def __init__(self, slide_path: str | Path) -> None:
        self._path = Path(slide_path)
        if not self._path.exists():
            raise FileNotFoundError(f"Slide path not found: {self._path}")

        metadata_file = self._path / "metadata.json"
        if not metadata_file.exists():
            raise FileNotFoundError(f"No metadata.json in {self._path}")

        with open(metadata_file) as f:
            self._meta = json.load(f)

        self._levels = self._build_levels()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def slide_path(self) -> Path:
        return self._path

    @property
    def source_file(self) -> str:
        return self._meta["source_file"]

    @property
    def source_mpp(self) -> float:
        return self._meta["source_mpp"]

    @property
    def pyramid_mpp(self) -> float:
        return self._meta["target_mpp"]

    @property
    def dimensions(self) -> tuple[int, int]:
        dims = self._meta["dimensions"]
        return (dims[0], dims[1])

    @property
    def tile_size(self) -> int:
        return self._meta["tile_size"]

    @property
    def levels(self) -> list[LevelInfo]:
        return list(self._levels)

    # ------------------------------------------------------------------
    # Level helpers
    # ------------------------------------------------------------------

    def _build_levels(self) -> list[LevelInfo]:
        """Build LevelInfo list with mpp populated."""
        levels = []
        for ldata in self._meta["levels"]:
            ds = ldata["downsample"]
            levels.append(
                LevelInfo(
                    level=ldata["level"],
                    downsample=ds,
                    cols=ldata["cols"],
                    rows=ldata["rows"],
                    mpp=self.pyramid_mpp * ds,
                )
            )
        return levels

    def level_for_mpp(self, target_mpp: float) -> int:
        """Return the coarsest level where ``level_mpp <= target_mpp``.

        Picks the level closest to ``target_mpp`` without exceeding it,
        preferring lower resolution for efficiency. If no level qualifies
        (all are coarser than ``target_mpp``), returns the highest-res level.
        """
        best: LevelInfo | None = None
        for info in self._levels:
            if info.mpp <= target_mpp:
                if best is None or info.mpp > best.mpp:
                    best = info
        if best is None:
            # Nothing qualifies — return highest-res level
            return self._levels[-1].level
        return best.level

    def level_mpp(self, level: int) -> float:
        """Return the MPP for a given level."""
        for info in self._levels:
            if info.level == level:
                return info.mpp
        raise ValueError(f"Unknown level: {level}")

    def level_downsample(self, level: int) -> float:
        """Return the downsample factor for a given level."""
        for info in self._levels:
            if info.level == level:
                return float(info.downsample)
        raise ValueError(f"Unknown level: {level}")

    def get_level_info(self, level: int) -> LevelInfo:
        """Return the ``LevelInfo`` for the given level index."""
        for info in self._levels:
            if info.level == level:
                return info
        raise ValueError(f"Unknown level: {level}")

    # ------------------------------------------------------------------
    # Tile access
    # ------------------------------------------------------------------

    def tile_path(self, level: int, col: int, row: int) -> Path | None:
        """Return the filesystem path of a tile, or None if it doesn't exist."""
        p = self._path / "tiles_files" / str(level) / f"{col}_{row}.jpg"
        return p if p.exists() else None

    def get_tile(self, level: int, col: int, row: int) -> np.ndarray | None:
        """Read a single tile as an RGB numpy array.

        Returns None if the tile file doesn't exist.
        """
        p = self.tile_path(level, col, row)
        if p is None:
            return None

        if is_vips_available() and pyvips is not None:
            vimg = pyvips.Image.new_from_file(str(p), access="sequential")
            return VIPSBackend.to_numpy(vimg)

        if PILImage is not None:
            pil_img = PILImage.open(p).convert("RGB")
            return np.array(pil_img)

        raise RuntimeError("Neither pyvips nor PIL available for tile decoding")

    def get_region(
        self, level: int, x: int, y: int, w: int, h: int
    ) -> np.ndarray:
        """Assemble a region from tiles. Coordinates are in level pixels.

        Returns an RGB numpy array of shape ``(h, w, 3)``.
        """
        ts = self.tile_size
        col_start = x // ts
        col_end = (x + w - 1) // ts + 1
        row_start = y // ts
        row_end = (y + h - 1) // ts + 1

        comp_w = (col_end - col_start) * ts
        comp_h = (row_end - row_start) * ts

        composite = np.full((comp_h, comp_w, 3), 255, dtype=np.uint8)

        for r in range(row_start, row_end):
            for c in range(col_start, col_end):
                tile = self.get_tile(level, c, r)
                if tile is not None:
                    py = (r - row_start) * ts
                    px = (c - col_start) * ts
                    th, tw = tile.shape[:2]
                    composite[py : py + th, px : px + tw] = tile

        # Crop to requested region
        ox = x - col_start * ts
        oy = y - row_start * ts
        return composite[oy : oy + h, ox : ox + w]

    def iter_tiles(
        self, level: int, roi: RegionOfInterest | None = None
    ) -> Iterator[TileInfo]:
        """Iterate over tiles at a given level.

        Args:
            level: Pyramid level index.
            roi: Optional region of interest in slide coordinates for filtering.

        Yields:
            TileInfo for each tile that intersects the ROI (or all tiles if roi is None).
        """
        info = self.get_level_info(level)
        ds = float(info.downsample)
        ts = self.tile_size

        for row in range(info.rows):
            for col in range(info.cols):
                # Tile bounds in slide coordinates
                sx = col * ts * ds
                sy = row * ts * ds
                sw = ts * ds
                sh = ts * ds
                bounds = (sx, sy, sw, sh)

                if roi is not None:
                    # Check intersection
                    if (
                        sx + sw <= roi.x
                        or sx >= roi.x + roi.w
                        or sy + sh <= roi.y
                        or sy >= roi.y + roi.h
                    ):
                        continue

                tile_img = self.get_tile(level, col, row)
                if tile_img is not None:
                    yield TileInfo(
                        col=col, row=row, image=tile_img, slide_bounds=bounds
                    )

    # ------------------------------------------------------------------
    # Coordinate helpers
    # ------------------------------------------------------------------

    def tile_bounds(
        self, level: int, col: int, row: int
    ) -> tuple[float, float, float, float]:
        """Return ``(x, y, w, h)`` of a tile in slide coordinates."""
        ds = self.level_downsample(level)
        ts = self.tile_size
        return (col * ts * ds, row * ts * ds, ts * ds, ts * ds)

    def to_slide(self, level: int, x: float, y: float) -> tuple[float, float]:
        """Convert level pixel coordinates to slide coordinates."""
        ds = self.level_downsample(level)
        return (x * ds, y * ds)

    def to_level(
        self, level: int, x_slide: float, y_slide: float
    ) -> tuple[float, float]:
        """Convert slide coordinates to level pixel coordinates."""
        ds = self.level_downsample(level)
        return (x_slide / ds, y_slide / ds)
