"""Test fixtures for FastPATH tests."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Generator

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from fastpath.preprocess.backends import VIPSBackend


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
    """Create a mock .fastpath directory structure using dzsave format."""
    fastpath_dir = temp_dir / "test_slide.fastpath"
    fastpath_dir.mkdir()

    # Create tiles_files directory (dzsave format)
    # Level 0 = lowest resolution (1x1 grid), level 2 = highest resolution (4x4 grid)
    tiles_dir = fastpath_dir / "tiles_files"
    tiles_dir.mkdir()

    # Level 2 (highest resolution): 4x4 grid of tiles
    dz_level2 = tiles_dir / "2"
    dz_level2.mkdir()
    for row in range(4):
        for col in range(4):
            vips_img = VIPSBackend.from_numpy(sample_rgb_array)
            VIPSBackend.save_jpeg(vips_img, dz_level2 / f"{col}_{row}.jpg", quality=95)

    # Level 1 (medium resolution): 2x2 grid
    dz_level1 = tiles_dir / "1"
    dz_level1.mkdir()
    resized = VIPSBackend.resize(VIPSBackend.from_numpy(sample_rgb_array), (512, 512))
    for row in range(2):
        for col in range(2):
            VIPSBackend.save_jpeg(resized, dz_level1 / f"{col}_{row}.jpg", quality=95)

    # Level 0 (lowest resolution): 1x1 grid
    dz_level0 = tiles_dir / "0"
    dz_level0.mkdir()
    VIPSBackend.save_jpeg(resized, dz_level0 / "0_0.jpg", quality=95)

    # Create thumbnail
    thumb = VIPSBackend.resize(VIPSBackend.from_numpy(sample_rgb_array), (256, 256))
    VIPSBackend.save_jpeg(thumb, fastpath_dir / "thumbnail.jpg", quality=90)

    # Create metadata with dzsave format marker
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
        "tile_format": "dzsave",
    }
    with open(fastpath_dir / "metadata.json", "w") as f:
        json.dump(metadata, f, indent=2)

    # Create annotations directory
    annotations_dir = fastpath_dir / "annotations"
    annotations_dir.mkdir()
    with open(annotations_dir / "default.geojson", "w") as f:
        json.dump({"type": "FeatureCollection", "features": []}, f)

    return fastpath_dir


@pytest.fixture
def sample_geojson_annotations() -> dict:
    """Sample GeoJSON annotation data."""
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": "ann_001",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [[100, 100], [200, 100], [200, 200], [100, 200], [100, 100]]
                    ],
                },
                "properties": {
                    "label": "Tumor",
                    "color": "#ff0000",
                    "notes": "Primary tumor region",
                },
            },
            {
                "type": "Feature",
                "id": "ann_002",
                "geometry": {"type": "Point", "coordinates": [300, 300]},
                "properties": {
                    "label": "Marker",
                    "color": "#00ff00",
                },
            },
        ],
    }
