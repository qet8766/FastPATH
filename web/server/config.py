from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ServerConfig:
    slide_dirs: list[Path]
    junction_dir: Path


def _split_paths(value: str) -> list[Path]:
    if not value:
        return []
    parts = [part.strip() for part in value.split(os.pathsep) if part.strip()]
    return [Path(part).expanduser().resolve() for part in parts]


def load_config() -> ServerConfig:
    slide_dirs = _split_paths(os.getenv("FASTPATH_WEB_SLIDE_DIRS", ""))
    if not slide_dirs:
        slide_dirs = [Path.cwd().resolve()]
    junction_dir = Path(os.getenv("FASTPATH_WEB_JUNCTION_DIR", ".fastpath_junctions"))
    junction_dir = junction_dir.expanduser().resolve()

    return ServerConfig(
        slide_dirs=slide_dirs,
        junction_dir=junction_dir,
    )
