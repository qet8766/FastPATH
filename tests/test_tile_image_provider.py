"""Tests for TileImageProvider (viewer tile images)."""

from __future__ import annotations

import gc
from pathlib import Path

import pytest
from PySide6.QtCore import QSize
from PySide6.QtGui import QImageReader

from fastpath.ui.providers import TileImageProvider
from fastpath_core import RustTileScheduler


def _qt_supports_jpeg() -> bool:
    fmts = {bytes(x).lower() for x in QImageReader.supportedImageFormats()}
    return b"jpg" in fmts or b"jpeg" in fmts


def test_tile_image_provider_no_copy_buffer_lifetime(
    monkeypatch, mock_fastpath_dir: Path, qapp  # noqa: ARG001
) -> None:
    """Ensure QImage keeps the tile buffer alive when copy is disabled.

    The provider builds a QImage from a Python bytes object returned by the Rust
    extension. With copy disabled, the QImage wraps external memory; this test
    ensures that buffer remains valid after requestImage returns.
    """
    monkeypatch.setenv("FASTPATH_FORCE_QIMAGE_COPY", "0")
    monkeypatch.setenv("FASTPATH_TILE_BUFFER", "0")

    scheduler = RustTileScheduler()
    scheduler.load(str(mock_fastpath_dir))

    provider = TileImageProvider(scheduler)
    img = provider.requestImage("2/0_0", QSize(), QSize())
    assert not img.isNull()

    # The bytes buffer is local to requestImage; if QImage doesn't hold a strong
    # reference, it may become invalid after GC and memory pressure.
    del provider
    gc.collect()

    first = bytes(img.bits()[:64])

    # Apply some memory pressure to increase the chance of catching UAF issues.
    junk = [bytearray(1024 * 1024) for _ in range(32)]  # ~32MB
    del junk
    gc.collect()

    second = bytes(img.bits()[:64])
    assert first == second


def test_tile_image_provider_tile_buffer_path(
    monkeypatch, mock_fastpath_dir: Path, qapp  # noqa: ARG001
) -> None:
    """Ensure the provider can use Rust's buffer protocol path."""
    monkeypatch.setenv("FASTPATH_TILE_BUFFER", "1")
    monkeypatch.setenv("FASTPATH_FORCE_QIMAGE_COPY", "0")

    scheduler = RustTileScheduler()
    scheduler.load(str(mock_fastpath_dir))

    provider = TileImageProvider(scheduler)
    img = provider.requestImage("2/0_0", QSize(), QSize())
    assert not img.isNull()

    del provider
    gc.collect()

    first = bytes(img.bits()[:64])
    junk = [bytearray(1024 * 1024) for _ in range(32)]  # ~32MB
    del junk
    gc.collect()
    second = bytes(img.bits()[:64])
    assert first == second


@pytest.mark.skipif(not _qt_supports_jpeg(), reason="Qt build does not support JPEG decoding")
def test_tile_image_provider_jpeg_mode_warms_l2_only(
    monkeypatch, mock_fastpath_dir: Path, qapp  # noqa: ARG001
) -> None:
    """In FASTPATH_TILE_MODE=jpeg, the provider should not populate Rust L1."""
    monkeypatch.setenv("FASTPATH_TILE_MODE", "jpeg")
    monkeypatch.setenv("FASTPATH_FORCE_QIMAGE_COPY", "0")

    scheduler = RustTileScheduler()
    scheduler.load(str(mock_fastpath_dir))

    stats = scheduler.cache_stats()
    assert stats["num_tiles"] == 0
    assert stats["l2_num_tiles"] == 0

    provider = TileImageProvider(scheduler)
    assert provider._tile_mode == "jpeg"  # sanity check

    img = provider.requestImage("2/0_0", QSize(), QSize())
    assert not img.isNull()

    stats = scheduler.cache_stats()
    assert stats["num_tiles"] == 0
    assert stats["l2_num_tiles"] >= 1
