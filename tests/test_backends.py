"""Tests for image processing backends."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from fastpath.preprocess.backends import (
    VIPSBackend,
    get_backend,
    get_backend_name,
    is_vips_available,
)


class TestVIPSBackend:
    """Tests for the PyVIPS backend."""

    def test_from_numpy_conversion(self, sample_rgb_array: np.ndarray):
        """Should convert numpy to vips format."""
        import pyvips

        result = VIPSBackend.from_numpy(sample_rgb_array)
        assert isinstance(result, pyvips.Image)
        assert result.width == sample_rgb_array.shape[1]
        assert result.height == sample_rgb_array.shape[0]
        assert result.bands == 3

    def test_to_numpy_conversion(self, sample_rgb_array: np.ndarray):
        """Should convert vips back to numpy."""
        vips_img = VIPSBackend.from_numpy(sample_rgb_array)
        result = VIPSBackend.to_numpy(vips_img)

        assert isinstance(result, np.ndarray)
        assert result.shape == sample_rgb_array.shape
        # Values should be identical (no compression)
        np.testing.assert_array_equal(result, sample_rgb_array)

    def test_save_and_load_jpeg(self, sample_rgb_array: np.ndarray, temp_dir: Path):
        """Should save and load JPEG correctly."""
        jpeg_path = temp_dir / "test_vips.jpg"
        vips_img = VIPSBackend.from_numpy(sample_rgb_array)

        VIPSBackend.save_jpeg(vips_img, jpeg_path, quality=95)
        assert jpeg_path.exists()

        loaded = VIPSBackend.load_jpeg(jpeg_path)
        assert loaded.width == sample_rgb_array.shape[1]
        assert loaded.height == sample_rgb_array.shape[0]

    def test_save_png(self, sample_rgb_array: np.ndarray, temp_dir: Path):
        """Should save PNG correctly."""
        png_path = temp_dir / "test_vips.png"
        vips_img = VIPSBackend.from_numpy(sample_rgb_array)

        VIPSBackend.save_png(vips_img, png_path)
        assert png_path.exists()

        loaded = VIPSBackend.load_jpeg(png_path)  # pyvips can load any format
        assert loaded.width == sample_rgb_array.shape[1]
        assert loaded.height == sample_rgb_array.shape[0]

    def test_resize(self, sample_rgb_array: np.ndarray):
        """Should resize using Lanczos3."""
        vips_img = VIPSBackend.from_numpy(sample_rgb_array)
        result = VIPSBackend.resize(vips_img, (256, 256))

        assert result.width == 256
        assert result.height == 256

    def test_resize_upscale(self, sample_rgb_array: np.ndarray):
        """Should handle upscaling."""
        vips_img = VIPSBackend.from_numpy(sample_rgb_array)
        result = VIPSBackend.resize(vips_img, (1024, 1024))

        assert result.width == 1024
        assert result.height == 1024

    def test_composite_2x2(self, sample_rgb_array: np.ndarray):
        """Should composite 4 tiles into 2x2 grid."""
        tile_size = 256
        # Create a smaller tile
        small_arr = sample_rgb_array[:tile_size, :tile_size, :]
        tile = VIPSBackend.from_numpy(small_arr)
        tiles = [tile, tile, tile, tile]
        bg_color = (255, 255, 255)

        result = VIPSBackend.composite_2x2(tiles, tile_size, bg_color)
        assert result.width == tile_size * 2
        assert result.height == tile_size * 2

    def test_composite_2x2_missing_tiles(self, sample_rgb_array: np.ndarray):
        """Should fill missing tiles with background."""
        tile_size = 256
        small_arr = sample_rgb_array[:tile_size, :tile_size, :]
        tile = VIPSBackend.from_numpy(small_arr)
        tiles = [tile, None, None, tile]
        bg_color = (255, 255, 255)

        result = VIPSBackend.composite_2x2(tiles, tile_size, bg_color)
        assert result.width == tile_size * 2
        assert result.height == tile_size * 2

    def test_new_rgb(self):
        """Should create a solid color image."""
        width, height = 100, 100
        color = (128, 64, 192)

        result = VIPSBackend.new_rgb(width, height, color)
        assert result.width == width
        assert result.height == height
        assert result.bands == 3

        # Check the color
        arr = VIPSBackend.to_numpy(result)
        assert arr[0, 0, 0] == color[0]
        assert arr[0, 0, 1] == color[1]
        assert arr[0, 0, 2] == color[2]


class TestBackendSelection:
    """Tests for backend selection logic."""

    def test_is_vips_available_returns_bool(self):
        """is_vips_available should return a boolean."""
        result = is_vips_available()
        assert isinstance(result, bool)

    def test_get_backend_name(self):
        """Should return 'PyVIPS'."""
        name = get_backend_name()
        assert name == "PyVIPS"

    def test_get_backend_returns_vips(self):
        """Should return VIPSBackend when vips is available."""
        backend = get_backend()
        assert backend is VIPSBackend
