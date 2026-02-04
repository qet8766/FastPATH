"""Tests for TileImageProvider (viewer tile images)."""

from __future__ import annotations

import gc
from pathlib import Path

from PySide6.QtCore import QSize

from fastpath.ui.providers import TileImageProvider
from fastpath_core import RustTileScheduler


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
