from __future__ import annotations

import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Tuple

from fastapi import Request
from fastapi.responses import FileResponse, Response, StreamingResponse

CHUNK_SIZE = 1024 * 1024


@dataclass(frozen=True)
class RangeSpec:
    start: int
    end: int

    @property
    def length(self) -> int:
        return self.end - self.start + 1


def _parse_range_header(range_header: str, size: int) -> Optional[RangeSpec]:
    if not range_header or not range_header.startswith("bytes="):
        return None

    raw_range = range_header[6:].split(",", 1)[0].strip()
    if "-" not in raw_range:
        return None

    start_str, end_str = raw_range.split("-", 1)
    if start_str == "":
        # suffix length
        try:
            length = int(end_str)
        except ValueError:
            return None
        if length <= 0:
            return None
        if length >= size:
            return RangeSpec(0, max(size - 1, 0))
        return RangeSpec(size - length, size - 1)

    try:
        start = int(start_str)
    except ValueError:
        return None

    if start >= size:
        return None

    if end_str == "":
        return RangeSpec(start, size - 1)

    try:
        end = int(end_str)
    except ValueError:
        return None

    if start > end:
        return None

    end = min(end, size - 1)
    return RangeSpec(start, end)


def _iter_file_range(path: Path, start: int, end: int) -> Iterable[bytes]:
    with path.open("rb") as handle:
        handle.seek(start)
        remaining = end - start + 1
        while remaining > 0:
            chunk = handle.read(min(CHUNK_SIZE, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


def _content_type_for(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".pack", ".idx"}:
        return "application/octet-stream"
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".png":
        return "image/png"
    return mimetypes.guess_type(path.as_posix())[0] or "application/octet-stream"


def _base_headers(path: Path) -> dict[str, str]:
    headers = {"Accept-Ranges": "bytes"}
    if path.suffix.lower() in {".pack", ".idx"}:
        headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return headers


def build_file_response(path: Path, request: Request) -> Response:
    size = path.stat().st_size
    range_header = request.headers.get("range")
    range_spec = _parse_range_header(range_header, size) if range_header else None
    media_type = _content_type_for(path)
    headers = _base_headers(path)

    if range_header and range_spec is None:
        headers["Content-Range"] = f"bytes */{size}"
        return Response(status_code=416, headers=headers)

    if range_spec:
        headers["Content-Range"] = f"bytes {range_spec.start}-{range_spec.end}/{size}"
        headers["Content-Length"] = str(range_spec.length)
        return StreamingResponse(
            _iter_file_range(path, range_spec.start, range_spec.end),
            status_code=206,
            media_type=media_type,
            headers=headers,
        )

    return FileResponse(path, media_type=media_type, headers=headers)
