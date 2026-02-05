"""Fixtures for E2E tests using pytest-playwright.

Starts a real uvicorn server with the SPA dist and a test slide directory,
then provides a live URL for Playwright to browse to.
"""

from __future__ import annotations

import json
import socket
import struct
import threading
from pathlib import Path

import pytest
import uvicorn

from web.server.config import ServerConfig
from web.server.main import create_app

_DIST_DIR = Path(__file__).resolve().parent.parent.parent / "client" / "dist"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def slide_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Create a minimal .fastpath slide directory for testing."""
    root = tmp_path_factory.mktemp("slides")
    fp_dir = root / "sample.fastpath"
    fp_dir.mkdir()

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
    (fp_dir / "metadata.json").write_text(json.dumps(metadata))
    # Minimal valid JPEG (SOI + EOI markers)
    (fp_dir / "thumbnail.jpg").write_bytes(b"\xff\xd8\xff\xd9")

    tiles_dir = fp_dir / "tiles"
    tiles_dir.mkdir()
    pack_bytes = b"tile-bytes"
    (tiles_dir / "level_0.pack").write_bytes(pack_bytes)

    header = b"FPLIDX1\x00" + struct.pack("<IHH", 1, 1, 1)
    entry = struct.pack("<QI", 0, len(pack_bytes))
    (tiles_dir / "level_0.idx").write_bytes(header + entry)

    return root


@pytest.fixture(scope="session")
def base_url(slide_root: Path) -> str:
    """Start a uvicorn server in a background thread and return its URL.

    Requires ``web/client/dist/`` to exist (run ``npm run build`` first).
    """
    if not _DIST_DIR.is_dir():
        pytest.skip(
            f"Vite dist not found at {_DIST_DIR}. "
            "Run 'cd web/client && npm run build' first."
        )

    port = _free_port()
    config = ServerConfig(slide_dirs=[slide_root], host="127.0.0.1", port=port)
    app = create_app(config)

    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    # Wait for server to start accepting connections
    import time

    for _ in range(50):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                break
        except OSError:
            time.sleep(0.1)
    else:
        pytest.fail("Server did not start")

    yield f"http://127.0.0.1:{port}"

    server.should_exit = True
    thread.join(timeout=5)
