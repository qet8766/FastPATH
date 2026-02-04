"""Test fixtures for FastPATH tests."""

from __future__ import annotations

import json
import struct
import tempfile
from pathlib import Path
from typing import Generator

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from fastpath.preprocess.backends import VIPSBackend

PACK_MAGIC = b"FPLIDX1\0"
PACK_HEADER = struct.Struct("<8sIHH")
PACK_ENTRY = struct.Struct("<QI")


@pytest.fixture(scope="session")
def qapp():
    """Create a Qt application for testing (shared across all test files)."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """Provide a temporary directory that's cleaned up after tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def sample_rgb_array() -> np.ndarray:
    """Create a simple RGB test image as numpy array with some patterns."""
    # Create 512x512 image with colored quadrants
    img = np.full((512, 512, 3), 255, dtype=np.uint8)

    # Top-left: red
    img[0:256, 0:256] = [200, 50, 50]

    # Top-right: green
    img[0:256, 256:512] = [50, 200, 50]

    # Bottom-left: blue
    img[256:512, 0:256] = [50, 50, 200]

    # Bottom-right: purple
    img[256:512, 256:512] = [150, 50, 150]

    return img


@pytest.fixture
def mock_fastpath_dir(temp_dir: Path, sample_rgb_array: np.ndarray) -> Path:
    """Create a mock .fastpath directory structure using packed tiles."""
    fastpath_dir = temp_dir / "test_slide.fastpath"
    fastpath_dir.mkdir()

    # Prepare JPEG bytes for each level
    vips_img = VIPSBackend.from_numpy(sample_rgb_array)
    high_bytes = vips_img.write_to_buffer(".jpg", Q=95)
    resized = VIPSBackend.resize(vips_img, (512, 512))
    mid_bytes = resized.write_to_buffer(".jpg", Q=95)
    low_bytes = mid_bytes

    level_bytes = {0: low_bytes, 1: mid_bytes, 2: high_bytes}
    levels = [
        {"level": 0, "cols": 1, "rows": 1},
        {"level": 1, "cols": 2, "rows": 2},
        {"level": 2, "cols": 4, "rows": 4},
    ]

    tiles_dir = fastpath_dir / "tiles"
    tiles_dir.mkdir()

    for info in levels:
        pack_path = tiles_dir / f"level_{info['level']}.pack"
        idx_path = tiles_dir / f"level_{info['level']}.idx"
        data = level_bytes[info["level"]]

        with open(pack_path, "wb") as pack_file, open(idx_path, "wb") as idx_file:
            idx_file.write(
                PACK_HEADER.pack(
                    PACK_MAGIC, 1, info["cols"], info["rows"]
                )
            )
            pack_offset = 0
            for _row in range(info["rows"]):
                for _col in range(info["cols"]):
                    pack_file.write(data)
                    idx_file.write(PACK_ENTRY.pack(pack_offset, len(data)))
                    pack_offset += len(data)

    # Create thumbnail
    thumb = VIPSBackend.resize(VIPSBackend.from_numpy(sample_rgb_array), (256, 256))
    VIPSBackend.save_jpeg(thumb, fastpath_dir / "thumbnail.jpg", quality=90)

    # Create metadata with pack format marker
    # Level 0 = lowest resolution (ds=4), level 2 = highest resolution (ds=1)
    metadata = {
        "version": "1.0",
        "source_file": "test_slide.svs",
        "source_mpp": 0.25,
        "target_mpp": 0.5,
        "target_magnification": 20,
        "tile_size": 512,
        "dimensions": [2048, 2048],
        "levels": [
            {"level": 0, "downsample": 4, "cols": 1, "rows": 1},
            {"level": 1, "downsample": 2, "cols": 2, "rows": 2},
            {"level": 2, "downsample": 1, "cols": 4, "rows": 4},
        ],
        "background_color": [255, 255, 255],
        "preprocessed_at": "2024-01-15T10:30:00Z",
        "tile_format": "pack_v2",
    }
    with open(fastpath_dir / "metadata.json", "w") as f:
        json.dump(metadata, f, indent=2)

    # Create annotations directory
    annotations_dir = fastpath_dir / "annotations"
    annotations_dir.mkdir()
    with open(annotations_dir / "default.geojson", "w") as f:
        json.dump({"type": "FeatureCollection", "features": []}, f)

    return fastpath_dir
