"""Tests for SlideContext original WSI access."""

from __future__ import annotations

from pathlib import Path
import types
from unittest.mock import MagicMock

import numpy as np
import pytest
from PIL import Image

import fastpath.plugins.context as context
from fastpath.plugins.context import SlideContext


def test_slide_to_wsi_scale(mock_fastpath_dir: Path):
    ctx = SlideContext(mock_fastpath_dir)
    assert ctx.slide_to_wsi_scale == pytest.approx(2.0)


def test_get_original_region_no_wsi(mock_fastpath_dir: Path, monkeypatch):
    ctx = SlideContext(mock_fastpath_dir)
    monkeypatch.setattr(context, "openslide", object())
    with pytest.raises(FileNotFoundError):
        ctx.get_original_region(0, 0, 10, 10)


def test_get_original_region_coords(mock_fastpath_dir: Path, monkeypatch):
    source_path = mock_fastpath_dir.parent / "test_slide.svs"
    source_path.write_bytes(b"")

    calls: dict[str, object] = {}

    def fake_open(path: str):
        slide = MagicMock()

        def _read_region(loc, level, size):
            calls["loc"] = loc
            calls["level"] = level
            calls["size"] = size
            return Image.new("RGBA", size, (0, 0, 0, 0))

        slide.read_region.side_effect = _read_region
        slide.close = MagicMock()
        return slide

    monkeypatch.setattr(context, "openslide", types.SimpleNamespace(OpenSlide=fake_open))

    ctx = SlideContext(mock_fastpath_dir)
    region = ctx.get_original_region(10, 20, 30, 40)

    assert calls["loc"] == (10, 20)
    assert calls["level"] == 0
    assert calls["size"] == (30, 40)
    assert region.shape == (40, 30, 3)


def test_close_wsi(mock_fastpath_dir: Path, monkeypatch):
    source_path = mock_fastpath_dir.parent / "test_slide.svs"
    source_path.write_bytes(b"")

    open_calls = {"count": 0}

    def fake_open(_path: str):
        open_calls["count"] += 1
        slide = MagicMock()
        slide.read_region.return_value = Image.new("RGBA", (4, 4), (0, 0, 0, 0))
        slide.close = MagicMock()
        return slide

    monkeypatch.setattr(context, "openslide", types.SimpleNamespace(OpenSlide=fake_open))

    ctx = SlideContext(mock_fastpath_dir)
    ctx.get_original_region(0, 0, 4, 4)
    assert open_calls["count"] == 1
    slide = ctx._wsi
    ctx.close_wsi()
    assert slide is not None
    slide.close.assert_called_once()

    ctx.get_original_region(0, 0, 4, 4)
    assert open_calls["count"] == 2
