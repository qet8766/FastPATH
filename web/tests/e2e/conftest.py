"""Fixtures for E2E tests using pytest-playwright.

Starts uvicorn for the API and Caddy for SPA + slides, then provides a live URL.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import threading
import time
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


def _wait_for_port(port: int, process: subprocess.Popen[str] | None = None) -> None:
    for _ in range(50):
        if process and process.poll() is not None:
            output = ""
            try:
                output = process.communicate(timeout=1)[0] or ""
            except Exception:
                output = ""
            pytest.fail(f"Process exited early while starting server:\n{output}")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                return
        except OSError:
            time.sleep(0.1)
    pytest.fail("Server did not start")


def _write_caddyfile(path: Path, port: int) -> None:
    lines = [
        "{",
        "    auto_https off",
        "}",
        "",
        f"http://127.0.0.1:{port} {{",
        "    handle /api/* {",
        "        reverse_proxy 127.0.0.1:{env.FASTPATH_WEB_API_PORT}",
        "    }",
        "",
        "    handle_path /slides/* {",
        "        @packs path *.pack *.idx",
        "        header @packs Cache-Control \"public, max-age=31536000\"",
        "        root * {env.FASTPATH_WEB_JUNCTION_DIR}",
        "        file_server",
        "    }",
        "",
        "    handle {",
        "        @assets path /assets/*",
        "        header @assets Cache-Control \"public, max-age=31536000, immutable\"",
        "",
        "        @sw path /sw.js",
        "        header @sw Cache-Control \"no-cache\"",
        "",
        "        root * {env.FASTPATH_WEB_DIST_DIR}",
        "        try_files {path} /index.html",
        "        file_server",
        "    }",
        "}",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


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
def slide_id(slide_root: Path) -> str:
    fp_dir = slide_root / "sample.fastpath"
    digest = hashlib.sha1(str(fp_dir).encode("utf-8")).hexdigest()
    return digest[:12]


class _UvicornRunner:
    """Run uvicorn in a background thread."""

    def __init__(self, app, host: str, port: int):
        config = uvicorn.Config(app, host=host, port=port, log_level="warning")
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._server.run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=5)


class _CaddyRunner:
    def __init__(self, caddyfile: Path, env: dict[str, str]):
        self._caddyfile = caddyfile
        self._env = env
        self._proc: subprocess.Popen[str] | None = None

    def start(self) -> None:
        self._proc = subprocess.Popen(
            ["caddy", "run", "--config", str(self._caddyfile), "--adapter", "caddyfile"],
            env=self._env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

    def stop(self) -> None:
        if not self._proc:
            return
        self._proc.terminate()
        try:
            self._proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._proc.kill()
            self._proc.wait(timeout=5)

    @property
    def process(self) -> subprocess.Popen[str] | None:
        return self._proc


@pytest.fixture(scope="session")
def base_url(slide_root: Path, tmp_path_factory: pytest.TempPathFactory) -> str:
    """Start uvicorn + Caddy and return the Caddy URL.

    Requires ``web/client/dist/`` to exist (run ``npm run build`` first).
    """
    if sys.platform != "win32":
        pytest.skip("Junction creation is Windows-only.")
    if shutil.which("caddy") is None:
        pytest.skip("Caddy not found in PATH.")
    if not _DIST_DIR.is_dir():
        pytest.skip(
            f"Vite dist not found at {_DIST_DIR}. "
            "Run 'cd web/client && npm run build' first."
        )

    api_port = _free_port()
    caddy_port = _free_port()
    junction_dir = slide_root.parent / "junctions"
    config = ServerConfig(
        slide_dirs=[slide_root],
        junction_dir=junction_dir,
    )
    app = create_app(config)

    api_runner = _UvicornRunner(app, "127.0.0.1", api_port)
    api_runner.start()
    _wait_for_port(api_port)

    caddy_dir = tmp_path_factory.mktemp("caddy")
    caddyfile = caddy_dir / "Caddyfile"
    _write_caddyfile(caddyfile, caddy_port)

    env = os.environ.copy()
    env["FASTPATH_WEB_DIST_DIR"] = str(_DIST_DIR)
    env["FASTPATH_WEB_JUNCTION_DIR"] = str(junction_dir)
    env["FASTPATH_WEB_API_PORT"] = str(api_port)

    caddy_runner = _CaddyRunner(caddyfile, env)
    try:
        caddy_runner.start()
        _wait_for_port(caddy_port, caddy_runner.process)
    except Exception:
        caddy_runner.stop()
        api_runner.stop()
        raise

    yield f"http://127.0.0.1:{caddy_port}"

    caddy_runner.stop()
    api_runner.stop()
