"""SlideContext — read-only access to a .fastpath pyramid directory.

Plain Python class (not QObject). Does NOT import ``core/slide.py``.
Reads the pyramid metadata and tiles directly from the filesystem.
"""

from __future__ import annotations

import io
import json
import logging
import mmap
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import numpy as np

from fastpath.core.types import LevelInfo
from fastpath.preprocess.backends import VIPSBackend, is_vips_available

from .types import RegionOfInterest

logger = logging.getLogger(__name__)

_PACK_MAGIC = b"FPTIDX1\0"
_PACK_HEADER = struct.Struct("<8sII")
_PACK_LEVEL = struct.Struct("<IIIQ")
_PACK_ENTRY = struct.Struct("<QII")

try:
    import pyvips
except (ImportError, OSError):
    pyvips = None

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
        self._pack_levels: dict[int, tuple[int, int, int]] = {}
        self._pack_index: bytes | None = None
        self._pack_entries_base = 0
        self._pack_file: io.BufferedReader | None = None
        self._pack_mmap: mmap.mmap | None = None

        if not self._path.exists():
            raise FileNotFoundError(f"Slide path not found: {self._path}")

        metadata_file = self._path / "metadata.json"
        if not metadata_file.exists():
            raise FileNotFoundError(f"No metadata.json in {self._path}")

        with open(metadata_file) as f:
            self._meta = json.load(f)

        if self._meta.get("tile_format") != "pack_v1":
            raise RuntimeError(
                f"Unsupported tile_format: {self._meta.get('tile_format')}"
            )

        if FastpathTileReader is not None:
            try:
                self._rust_reader = FastpathTileReader(str(self._path))
            except Exception as e:
                logger.warning(
                    "Failed to initialize Rust tile reader; falling back to Python pack reader: %s",
                    e,
                )
                self._rust_reader = None
        if self._rust_reader is None:
            self._load_pack()

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

    def _load_pack(self) -> None:
        idx_path = self._path / "tiles.idx"
        pack_path = self._path / "tiles.pack"

        if not idx_path.exists():
            raise FileNotFoundError(f"No tiles.idx in {self._path}")
        if not pack_path.exists():
            raise FileNotFoundError(f"No tiles.pack in {self._path}")

        data = idx_path.read_bytes()
        if len(data) < _PACK_HEADER.size:
            raise RuntimeError("tiles.idx is too small")

        magic, version, level_count = _PACK_HEADER.unpack_from(data, 0)
        if magic != _PACK_MAGIC:
            raise RuntimeError("tiles.idx magic mismatch")
        if version != 1:
            raise RuntimeError(f"Unsupported tiles.idx version: {version}")
        if level_count == 0:
            raise RuntimeError("tiles.idx has no levels")

        levels_offset = _PACK_HEADER.size
        levels_size = level_count * _PACK_LEVEL.size
        if len(data) < levels_offset + levels_size:
            raise RuntimeError("tiles.idx missing level table")

        entries_base = levels_offset + levels_size
        entries_len = len(data) - entries_base

        for i in range(level_count):
            level, cols, rows, entry_offset = _PACK_LEVEL.unpack_from(
                data, levels_offset + i * _PACK_LEVEL.size
            )
            entry_count = cols * rows
            end = entry_offset + entry_count * _PACK_ENTRY.size
            if end > entries_len:
                raise RuntimeError(
                    f"tiles.idx entry range out of bounds for level {level}"
                )
            self._pack_levels[level] = (cols, rows, entry_offset)

        self._pack_index = data
        self._pack_entries_base = entries_base
        self._pack_file = open(pack_path, "rb")
        self._pack_mmap = mmap.mmap(self._pack_file.fileno(), 0, access=mmap.ACCESS_READ)

    def close_pack(self) -> None:
        self._rust_reader = None
        if self._pack_mmap is not None:
            self._pack_mmap.close()
            self._pack_mmap = None
        if self._pack_file is not None:
            self._pack_file.close()
            self._pack_file = None

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
        self.close_pack()

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

    def _tile_bytes(self, level: int, col: int, row: int) -> bytes | None:
        info = self._pack_levels.get(level)
        if info is None:
            return None

        cols, rows, entry_offset = info
        if col < 0 or row < 0 or col >= cols or row >= rows:
            return None

        if self._pack_index is None or self._pack_mmap is None:
            return None

        idx = row * cols + col
        entry_pos = self._pack_entries_base + entry_offset + idx * _PACK_ENTRY.size
        if entry_pos + _PACK_ENTRY.size > len(self._pack_index):
            return None

        offset, length, _ = _PACK_ENTRY.unpack_from(self._pack_index, entry_pos)
        if length == 0:
            return None

        if offset + length > len(self._pack_mmap):
            return None

        return self._pack_mmap[offset : offset + length]

    def get_tile(self, level: int, col: int, row: int) -> np.ndarray | None:
        """Read a single tile as an RGB numpy array.

        Returns None if the tile file doesn't exist.
        """
        if self._rust_reader is not None:
            if level < 0 or col < 0 or row < 0:
                return None
            tile_data = self._rust_reader.decode_tile(level, col, row)
            if tile_data is None:
                return None
            data, width, height = tile_data
            return np.frombuffer(data, dtype=np.uint8).reshape((height, width, 3))

        data = self._tile_bytes(level, col, row)
        if data is None:
            return None

        if is_vips_available() and pyvips is not None:
            vimg = pyvips.Image.new_from_buffer(data, "", access="sequential")
            return VIPSBackend.to_numpy(vimg)

        if PILImage is not None:
            pil_img = PILImage.open(io.BytesIO(data)).convert("RGB")
            return np.array(pil_img)

        raise RuntimeError("Neither pyvips nor PIL available for tile decoding")

    def get_region(
        self, level: int, x: int, y: int, w: int, h: int
    ) -> np.ndarray:
        """Assemble a region from tiles. Coordinates are in level pixels.

        Returns an RGB numpy array of shape ``(h, w, 3)``.
        """
        if self._rust_reader is not None:
            if w <= 0 or h <= 0:
                raise ValueError("Region width and height must be positive")
            if level < 0:
                return np.full((h, w, 3), 255, dtype=np.uint8)
            data = self._rust_reader.decode_region(level, x, y, w, h)
            return np.frombuffer(data, dtype=np.uint8).reshape((h, w, 3))

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
