"""SlideContext — read-only access to a .fastpath pyramid directory.

Plain Python class (not QObject). Does NOT import ``ui/slide.py``.
Reads the pyramid metadata and tiles directly from the filesystem.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import numpy as np

from fastpath.types import LevelInfo

from .types import RegionOfInterest

try:
    from PIL import Image as PILImage
except ImportError:
    PILImage = None

try:
    import openslide
except ImportError:
    openslide = None

try:
    from fastpath_core import FastpathTileReader
except (ImportError, OSError):
    FastpathTileReader = None


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
        # Initialize all fields up front so __del__ is safe even if __init__ raises.
        self._meta: dict = {}
        self._levels: list[LevelInfo] = []
        self._wsi: openslide.OpenSlide | None = None
        self._wsi_path: Path | None = None
        self._rust_reader: FastpathTileReader | None = None

        if not self._path.exists():
            raise FileNotFoundError(f"Slide path not found: {self._path}")

        metadata_file = self._path / "metadata.json"
        if not metadata_file.exists():
            raise FileNotFoundError(f"No metadata.json in {self._path}")

        with open(metadata_file) as f:
            self._meta = json.load(f)

        if self._meta.get("tile_format") != "pack_v2":
            raise RuntimeError(
                f"Unsupported tile_format: {self._meta.get('tile_format')}"
            )

        if FastpathTileReader is None:
            raise RuntimeError(
                "fastpath_core is required to read pack_v2 tiles; Rust extension is missing"
            )

        self._rust_reader = FastpathTileReader(str(self._path))

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
    def slide_to_wsi_scale(self) -> float:
        """Scale factor: slide coords -> WSI level-0 pixels."""
        if self.source_mpp <= 0:
            return 1.0
        return self.pyramid_mpp / self.source_mpp

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

    def close_wsi(self) -> None:
        """Close the OpenSlide handle if open."""
        if self._wsi is not None:
            try:
                self._wsi.close()
            except Exception:
                pass
            self._wsi = None
            self._wsi_path = None

    def close(self) -> None:
        self.close_wsi()
        self._rust_reader = None

    def __del__(self) -> None:
        self.close()

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

    def get_tile(self, level: int, col: int, row: int) -> np.ndarray | None:
        """Read a single tile as an RGB numpy array.

        Returns None if the tile file doesn't exist.
        """
        if self._rust_reader is None:
            raise RuntimeError("fastpath_core is required to decode tiles")
        if level < 0 or col < 0 or row < 0:
            return None
        tile_data = self._rust_reader.decode_tile(level, col, row)
        if tile_data is None:
            return None
        data, width, height = tile_data
        return np.frombuffer(data, dtype=np.uint8).reshape((height, width, 3))

    def get_region(
        self, level: int, x: int, y: int, w: int, h: int
    ) -> np.ndarray:
        """Assemble a region from tiles. Coordinates are in level pixels.

        Returns an RGB numpy array of shape ``(h, w, 3)``.
        """
        if self._rust_reader is None:
            raise RuntimeError("fastpath_core is required to decode regions")
        if w <= 0 or h <= 0:
            raise ValueError("Region width and height must be positive")
        if level < 0:
            return np.full((h, w, 3), 255, dtype=np.uint8)
        data = self._rust_reader.decode_region(level, x, y, w, h)
        return np.frombuffer(data, dtype=np.uint8).reshape((h, w, 3))

    # ------------------------------------------------------------------
    # Original WSI access
    # ------------------------------------------------------------------

    def _resolve_source_path(self) -> Path:
        source = Path(self.source_file)
        if source.is_absolute() and source.exists():
            return source

        candidate = self._path.parent / source
        if candidate.exists():
            return candidate

        candidate = self._path / source
        if candidate.exists():
            return candidate

        raise FileNotFoundError(
            f"Source WSI not found: {self.source_file} (searched {self._path.parent} and {self._path})"
        )

    def _open_wsi(self) -> "openslide.OpenSlide":
        if self._wsi is not None:
            return self._wsi

        if openslide is None:
            raise RuntimeError("openslide-python is not available")
        if PILImage is None:
            raise RuntimeError("Pillow is required for WSI reading")

        source_path = self._resolve_source_path()
        self._wsi = openslide.OpenSlide(str(source_path))
        self._wsi_path = source_path
        return self._wsi

    def get_original_region(self, x: int, y: int, w: int, h: int) -> np.ndarray:
        """Read a region from the original WSI at level 0.

        Coordinates are in WSI level-0 pixels. Returns RGB array (h, w, 3).
        """
        if w <= 0 or h <= 0:
            raise ValueError("Region width and height must be positive")

        wsi = self._open_wsi()
        region = wsi.read_region((int(x), int(y)), 0, (int(w), int(h)))
        if region.mode != "RGBA":
            region = region.convert("RGBA")

        background = PILImage.new("RGBA", region.size, (255, 255, 255, 255))
        background.alpha_composite(region)
        rgb = background.convert("RGB")
        return np.array(rgb)

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
