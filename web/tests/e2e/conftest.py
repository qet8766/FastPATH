"""Fixtures for E2E tests using pytest-playwright.

Starts a real Hypercorn server with the SPA dist and a test slide directory,
then provides a live URL for Playwright to browse to.
"""

from __future__ import annotations

import asyncio
import json
import socket
import struct
import threading
from pathlib import Path

import pytest
from hypercorn.asyncio import serve
from hypercorn.config import Config as HypercornConfig

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


class _ServerRunner:
    """Run Hypercorn in a background thread with its own event loop."""

    def __init__(self, app, host: str, port: int):
        self.app = app
        self.host = host
        self.port = port
        self._loop: asyncio.AbstractEventLoop | None = None
        self._shutdown_event: asyncio.Event | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._shutdown_event = asyncio.Event()

        hconfig = HypercornConfig()
        hconfig.bind = [f"{self.host}:{self.port}"]
        hconfig.loglevel = "WARNING"

        self._loop.run_until_complete(
            serve(self.app, hconfig, shutdown_trigger=self._shutdown_event.wait)
        )

    def stop(self) -> None:
        if self._loop and self._shutdown_event:
            self._loop.call_soon_threadsafe(self._shutdown_event.set)
        if self._thread:
            self._thread.join(timeout=5)


@pytest.fixture(scope="session")
def base_url(slide_root: Path) -> str:
    """Start a Hypercorn server in a background thread and return its URL.

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

    runner = _ServerRunner(app, "127.0.0.1", port)
    runner.start()

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

    runner.stop()
