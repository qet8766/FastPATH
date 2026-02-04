from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from web.server.config import ServerConfig
from web.server.main import create_app


@pytest.fixture()
def slide_root(tmp_path: Path) -> Path:
    root = tmp_path / "slides"
    root.mkdir()
    fastpath_dir = root / "sample.fastpath"
    fastpath_dir.mkdir()

    metadata = {
        "version": "0.1.0",
        "source_file": "sample.svs",
        "source_mpp": 0.5,
        "target_mpp": 0.5,
        "target_magnification": 20.0,
        "tile_size": 512,
        "dimensions": [1024, 1024],
        "levels": [{"level": 0, "downsample": 1, "cols": 1, "rows": 1}],
        "background_color": [0, 0, 0],
        "preprocessed_at": "2024-01-01",
        "tile_format": "pack_v2",
    }
    (fastpath_dir / "metadata.json").write_text(json.dumps(metadata))
    (fastpath_dir / "thumbnail.jpg").write_bytes(b"\xff\xd8\xff\xd9")

    tiles_dir = fastpath_dir / "tiles"
    tiles_dir.mkdir()
    pack_bytes = b"tile-bytes"
    (tiles_dir / "level_0.pack").write_bytes(pack_bytes)

    header = b"FPLIDX1\x00" + struct.pack("<IHH", 1, 1, 1)
    entry = struct.pack("<QI", 0, len(pack_bytes))
    (tiles_dir / "level_0.idx").write_bytes(header + entry)

    return root


@pytest.fixture()
def app_context(slide_root: Path):
    app = create_app(ServerConfig(slide_dirs=[slide_root]))
    slide_id = next(iter(app.state.slides))
    return app, slide_id


@pytest.fixture()
def client(app_context) -> TestClient:
    app, _slide_id = app_context
    return TestClient(app)


@pytest.fixture()
def slide_id(app_context) -> str:
    _app, slide_id = app_context
    return slide_id
