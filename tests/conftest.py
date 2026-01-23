"""Test fixtures for FastPATH tests."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Generator

import numpy as np
import pytest

from fastpath.preprocess.backends import VIPSBackend, is_vips_available


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
    # dzsave level numbering: 0 = smallest, N = largest (full resolution)
    # FastPATH level 0 = dzsave level 2 (4x4 grid)
    # FastPATH level 1 = dzsave level 1 (2x2 grid)
    # FastPATH level 2 = dzsave level 0 (1x1 grid)
    tiles_dir = fastpath_dir / "tiles_files"
    tiles_dir.mkdir()

    # Also create levels directory (empty, for compatibility check)
    levels_dir = fastpath_dir / "levels"
    levels_dir.mkdir()

    # Use pyvips if available, otherwise use raw JPEG writing
    if is_vips_available():
        # dzsave level 2 (FastPATH level 0): 4x4 grid of tiles
        dz_level2 = tiles_dir / "2"
        dz_level2.mkdir()
        for row in range(4):
            for col in range(4):
                vips_img = VIPSBackend.from_numpy(sample_rgb_array)
                VIPSBackend.save_jpeg(vips_img, dz_level2 / f"{col}_{row}.jpg", quality=95)

        # dzsave level 1 (FastPATH level 1): 2x2 grid
        dz_level1 = tiles_dir / "1"
        dz_level1.mkdir()
        resized = VIPSBackend.resize(VIPSBackend.from_numpy(sample_rgb_array), (512, 512))
        for row in range(2):
            for col in range(2):
                VIPSBackend.save_jpeg(resized, dz_level1 / f"{col}_{row}.jpg", quality=95)

        # dzsave level 0 (FastPATH level 2): 1x1 grid
        dz_level0 = tiles_dir / "0"
        dz_level0.mkdir()
        VIPSBackend.save_jpeg(resized, dz_level0 / "0_0.jpg", quality=95)

        # Create thumbnail
        thumb = VIPSBackend.resize(VIPSBackend.from_numpy(sample_rgb_array), (256, 256))
        VIPSBackend.save_jpeg(thumb, fastpath_dir / "thumbnail.jpg", quality=90)
    else:
        # Fallback: create minimal valid JPEG files
        # This is a minimal valid JPEG for testing when pyvips is unavailable
        def create_minimal_jpeg(path: Path) -> None:
            # Create a minimal valid JPEG (1x1 pixel)
            # This is just for test structure, not actual image content
            jpeg_data = bytes([
                0xFF, 0xD8, 0xFF, 0xE0, 0x00, 0x10, 0x4A, 0x46, 0x49, 0x46, 0x00, 0x01,
                0x01, 0x00, 0x00, 0x01, 0x00, 0x01, 0x00, 0x00, 0xFF, 0xDB, 0x00, 0x43,
                0x00, 0x08, 0x06, 0x06, 0x07, 0x06, 0x05, 0x08, 0x07, 0x07, 0x07, 0x09,
                0x09, 0x08, 0x0A, 0x0C, 0x14, 0x0D, 0x0C, 0x0B, 0x0B, 0x0C, 0x19, 0x12,
                0x13, 0x0F, 0x14, 0x1D, 0x1A, 0x1F, 0x1E, 0x1D, 0x1A, 0x1C, 0x1C, 0x20,
                0x24, 0x2E, 0x27, 0x20, 0x22, 0x2C, 0x23, 0x1C, 0x1C, 0x28, 0x37, 0x29,
                0x2C, 0x30, 0x31, 0x34, 0x34, 0x34, 0x1F, 0x27, 0x39, 0x3D, 0x38, 0x32,
                0x3C, 0x2E, 0x33, 0x34, 0x32, 0xFF, 0xC0, 0x00, 0x0B, 0x08, 0x00, 0x01,
                0x00, 0x01, 0x01, 0x01, 0x11, 0x00, 0xFF, 0xC4, 0x00, 0x1F, 0x00, 0x00,
                0x01, 0x05, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x00, 0x00, 0x00, 0x00,
                0x00, 0x00, 0x00, 0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08,
                0x09, 0x0A, 0x0B, 0xFF, 0xC4, 0x00, 0xB5, 0x10, 0x00, 0x02, 0x01, 0x03,
                0x03, 0x02, 0x04, 0x03, 0x05, 0x05, 0x04, 0x04, 0x00, 0x00, 0x01, 0x7D,
                0x01, 0x02, 0x03, 0x00, 0x04, 0x11, 0x05, 0x12, 0x21, 0x31, 0x41, 0x06,
                0x13, 0x51, 0x61, 0x07, 0x22, 0x71, 0x14, 0x32, 0x81, 0x91, 0xA1, 0x08,
                0x23, 0x42, 0xB1, 0xC1, 0x15, 0x52, 0xD1, 0xF0, 0x24, 0x33, 0x62, 0x72,
                0x82, 0x09, 0x0A, 0x16, 0x17, 0x18, 0x19, 0x1A, 0x25, 0x26, 0x27, 0x28,
                0x29, 0x2A, 0x34, 0x35, 0x36, 0x37, 0x38, 0x39, 0x3A, 0x43, 0x44, 0x45,
                0x46, 0x47, 0x48, 0x49, 0x4A, 0x53, 0x54, 0x55, 0x56, 0x57, 0x58, 0x59,
                0x5A, 0x63, 0x64, 0x65, 0x66, 0x67, 0x68, 0x69, 0x6A, 0x73, 0x74, 0x75,
                0x76, 0x77, 0x78, 0x79, 0x7A, 0x83, 0x84, 0x85, 0x86, 0x87, 0x88, 0x89,
                0x8A, 0x92, 0x93, 0x94, 0x95, 0x96, 0x97, 0x98, 0x99, 0x9A, 0xA2, 0xA3,
                0xA4, 0xA5, 0xA6, 0xA7, 0xA8, 0xA9, 0xAA, 0xB2, 0xB3, 0xB4, 0xB5, 0xB6,
                0xB7, 0xB8, 0xB9, 0xBA, 0xC2, 0xC3, 0xC4, 0xC5, 0xC6, 0xC7, 0xC8, 0xC9,
                0xCA, 0xD2, 0xD3, 0xD4, 0xD5, 0xD6, 0xD7, 0xD8, 0xD9, 0xDA, 0xE1, 0xE2,
                0xE3, 0xE4, 0xE5, 0xE6, 0xE7, 0xE8, 0xE9, 0xEA, 0xF1, 0xF2, 0xF3, 0xF4,
                0xF5, 0xF6, 0xF7, 0xF8, 0xF9, 0xFA, 0xFF, 0xDA, 0x00, 0x08, 0x01, 0x01,
                0x00, 0x00, 0x3F, 0x00, 0xFB, 0xD5, 0xDB, 0x20, 0xBA, 0xA3, 0xAE, 0xF8,
                0xFF, 0xD9
            ])
            path.write_bytes(jpeg_data)

        # dzsave level 2 (FastPATH level 0): 4x4 grid of tiles
        dz_level2 = tiles_dir / "2"
        dz_level2.mkdir()
        for row in range(4):
            for col in range(4):
                create_minimal_jpeg(dz_level2 / f"{col}_{row}.jpg")

        # dzsave level 1 (FastPATH level 1): 2x2 grid
        dz_level1 = tiles_dir / "1"
        dz_level1.mkdir()
        for row in range(2):
            for col in range(2):
                create_minimal_jpeg(dz_level1 / f"{col}_{row}.jpg")

        # dzsave level 0 (FastPATH level 2): 1x1 grid
        dz_level0 = tiles_dir / "0"
        dz_level0.mkdir()
        create_minimal_jpeg(dz_level0 / "0_0.jpg")

        # Create thumbnail
        create_minimal_jpeg(fastpath_dir / "thumbnail.jpg")

    # Create metadata with dzsave format marker
    metadata = {
        "version": "1.0",
        "source_file": "test_slide.svs",
        "source_mpp": 0.25,
        "target_mpp": 0.5,
        "target_magnification": 20,
        "tile_size": 512,
        "dimensions": [2048, 2048],
        "levels": [
            {"level": 0, "downsample": 1, "cols": 4, "rows": 4},
            {"level": 1, "downsample": 2, "cols": 2, "rows": 2},
            {"level": 2, "downsample": 4, "cols": 1, "rows": 1},
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
