"""Path utilities for bridging QML URLs and local filesystem paths."""

from __future__ import annotations

from pathlib import Path

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

