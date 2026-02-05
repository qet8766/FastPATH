from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ServerConfig:
    slide_dirs: list[Path]
    host: str = "0.0.0.0"
    port: int = 8000


def _split_paths(value: str) -> list[Path]:
    if not value:
        return []
    parts = [part.strip() for part in value.split(os.pathsep) if part.strip()]
    return [Path(part).expanduser().resolve() for part in parts]


def load_config() -> ServerConfig:
    slide_dirs = _split_paths(os.getenv("FASTPATH_WEB_SLIDE_DIRS", ""))
    if not slide_dirs:
        slide_dirs = [Path.cwd().resolve()]
    host = os.getenv("FASTPATH_WEB_HOST", "0.0.0.0")
    port_str = os.getenv("FASTPATH_WEB_PORT", "8000")
    try:
        port = int(port_str)
    except ValueError:
        port = 8000
    return ServerConfig(slide_dirs=slide_dirs, host=host, port=port)
