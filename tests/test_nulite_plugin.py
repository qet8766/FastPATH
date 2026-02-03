"""Tests for NuLite plugin helpers."""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("torch")
pytest.importorskip("timm")

from fastpath.plugins.nulite.plugin import NuLitePlugin, _unflatten_dict


def test_unflatten_dict():
    data = {"model.backbone": "fastvit_t8", "transformations.normalize.mean": [0.1, 0.2, 0.3]}
    nested = _unflatten_dict(data)
    assert nested["model"]["backbone"] == "fastvit_t8"
    assert nested["transformations"]["normalize"]["mean"] == [0.1, 0.2, 0.3]


def test_num_patches_small_roi():
    assert NuLitePlugin._num_patches(512) == 1


def test_num_patches_stride_roi():
    assert NuLitePlugin._num_patches(1984) == 2


def test_centroid_ownership_core():
    plugin = NuLitePlugin()
    cells = [
        {
            "centroid": np.array([100.0, 100.0], dtype=np.float32),
            "patch_origin": (0.0, 0.0),
        }
    ]
    kept = plugin._deduplicate_cells(cells, 0, 0, 1024, 1024)
    assert len(kept) == 1


def test_centroid_ownership_margin_discard():
    plugin = NuLitePlugin()
    cells = [
        {
            "centroid": np.array([970.0, 970.0], dtype=np.float32),
            "patch_origin": (960.0, 960.0),
        }
    ]
    kept = plugin._deduplicate_cells(cells, 0, 0, 2048, 2048)
    assert len(kept) == 0


def test_centroid_ownership_edge_patch():
    plugin = NuLitePlugin()
    cells = [
        {
            "centroid": np.array([10.0, 10.0], dtype=np.float32),
            "patch_origin": (0.0, 0.0),
        }
    ]
    kept = plugin._deduplicate_cells(cells, 0, 0, 2048, 2048)
    assert len(kept) == 1
