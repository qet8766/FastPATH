"""Path utilities for bridging QML URLs and local filesystem paths."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from PySide6.QtCore import QUrl


def to_local_path(value: str | Path) -> Path:
    """Convert a QML/Python path-or-URL into a local filesystem ``Path``.

    QML file/folder dialogs often pass ``file:///...`` URLs. This helper converts
    them to native filesystem paths using ``QUrl.toLocalFile()`` while preserving
    plain paths unchanged.
    """
    if isinstance(value, Path):
        return value

    text = str(value).strip()
    if not text:
        return Path()

    url = QUrl(text)
    if url.isValid() and url.isLocalFile():
        local = url.toLocalFile()
        if local:
            return Path(local)

    return Path(text)


def atomic_json_save(path: Path, data: Any) -> None:
    """Atomically write JSON data to a file.

    Writes to a temp file in the same directory, then replaces the target.
    ``os.replace()`` is atomic on both POSIX and Windows (same filesystem).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=path.parent, suffix=".tmp", prefix=path.stem
    )
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

