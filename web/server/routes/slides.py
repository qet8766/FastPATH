from __future__ import annotations

import hashlib
import json
import logging
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)
_REPARSE_POINT = 0x400


@dataclass(frozen=True)
class SlideRecord:
    slide_id: str
    name: str
    dir_path: Path
    metadata: dict
    thumbnail_path: Path


def _slide_id_for_path(path: Path) -> str:
    digest = hashlib.sha1(str(path).encode("utf-8")).hexdigest()
    return digest[:12]


def _display_name(metadata: dict, fallback: str) -> str:
    source_file = metadata.get("source_file")
    if source_file:
        return Path(source_file).stem
    return fallback


def _iter_fastpath_dirs(slide_dirs: Iterable[Path]) -> Iterable[Path]:
    for base_dir in slide_dirs:
        if not base_dir.exists():
            logger.warning("Slide dir does not exist: %s", base_dir)
            continue
        yield from base_dir.rglob("*.fastpath")


def build_slide_index(slide_dirs: Iterable[Path]) -> dict[str, SlideRecord]:
    slides: dict[str, SlideRecord] = {}

    for fastpath_dir in _iter_fastpath_dirs(slide_dirs):
        metadata_path = fastpath_dir / "metadata.json"
        thumbnail_path = fastpath_dir / "thumbnail.jpg"

        if not metadata_path.exists() or not thumbnail_path.exists():
            logger.warning("Skipping incomplete slide: %s", fastpath_dir)
            continue

        try:
            metadata = json.loads(metadata_path.read_text())
        except json.JSONDecodeError:
            logger.warning("Skipping invalid metadata: %s", metadata_path)
            continue

        if metadata.get("tile_format") != "pack_v2":
            logger.warning("Skipping unsupported tile_format: %s", metadata.get("tile_format"))
            continue

        slide_id = _slide_id_for_path(fastpath_dir)
        name = _display_name(metadata, fastpath_dir.stem)
        slides[slide_id] = SlideRecord(
            slide_id=slide_id,
            name=name,
            dir_path=fastpath_dir,
            metadata=metadata,
            thumbnail_path=thumbnail_path,
        )

    return slides


def _is_reparse_point(path: Path) -> bool:
    try:
        return bool(path.lstat().st_file_attributes & _REPARSE_POINT)
    except FileNotFoundError:
        return False


def create_junctions(slides: dict[str, SlideRecord], junction_dir: Path) -> None:
    if sys.platform != "win32":
        raise RuntimeError("Slide junctions are only supported on Windows.")

    junction_dir = junction_dir.expanduser().resolve()
    junction_dir.mkdir(parents=True, exist_ok=True)

    desired_ids = set(slides.keys())
    for entry in junction_dir.iterdir():
        if entry.name in desired_ids:
            continue
        if _is_reparse_point(entry):
            try:
                entry.rmdir()
            except OSError as exc:
                logger.warning("Failed to remove stale junction %s: %s", entry, exc)

    for slide_id, record in slides.items():
        link = junction_dir / slide_id
        if link.exists() or link.is_symlink():
            if _is_reparse_point(link):
                continue
            logger.warning("Junction path exists and is not a junction: %s", link)
            continue
        target = record.dir_path.resolve()
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            check=True,
            capture_output=True,
            text=True,
        )


def create_slides_router(slides: dict[str, SlideRecord]) -> APIRouter:
    router = APIRouter()

    @router.get("/api/slides")
    def list_slides() -> JSONResponse:
        response = []
        for record in slides.values():
            metadata = record.metadata
            response.append(
                {
                    "hash": record.slide_id,
                    "name": record.name,
                    "dimensions": metadata.get("dimensions"),
                    "levels": metadata.get("levels"),
                    "mpp": metadata.get("target_mpp") or metadata.get("source_mpp"),
                    "thumbnailUrl": f"/slides/{record.slide_id}/thumbnail.jpg",
                }
            )
        return JSONResponse(
            content=response,
            headers={"Cache-Control": "public, max-age=60"},
        )

    @router.get("/api/slides/{slide_id}/metadata")
    def get_metadata(slide_id: str) -> JSONResponse:
        record = slides.get(slide_id)
        if not record:
            raise HTTPException(status_code=404, detail="Slide not found")
        content = dict(record.metadata)
        pack_sizes: dict[str, int] = {}
        tiles_dir = record.dir_path / "tiles"
        for level_info in content.get("levels", []):
            level_num = level_info.get("level")
            if level_num is None:
                continue
            pack_file = tiles_dir / f"level_{level_num}.pack"
            if pack_file.exists():
                pack_sizes[str(level_num)] = pack_file.stat().st_size
        content["pack_sizes"] = pack_sizes
        return JSONResponse(
            content=content,
            headers={"Cache-Control": "public, max-age=3600"},
        )

    return router
