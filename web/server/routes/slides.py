from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


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


def create_slides_router(slides: dict[str, SlideRecord]) -> APIRouter:
    router = APIRouter()

    @router.get("/api/slides")
    def list_slides() -> list[dict]:
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
        return response

    @router.get("/api/slides/{slide_id}/metadata")
    def get_metadata(slide_id: str) -> JSONResponse:
        record = slides.get(slide_id)
        if not record:
            raise HTTPException(status_code=404, detail="Slide not found")
        return JSONResponse(record.metadata)

    return router
