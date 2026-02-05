from __future__ import annotations

from pathlib import Path


def _is_reparse_point(path: Path) -> bool:
    return bool(path.lstat().st_file_attributes & 0x400)


def test_list_slides(client):
    response = client.get("/api/slides")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["hash"]
    assert data[0]["thumbnailUrl"].endswith("/thumbnail.jpg")


def test_get_metadata(client, slide_id):
    response = client.get(f"/api/slides/{slide_id}/metadata")
    assert response.status_code == 200
    data = response.json()
    assert data["tile_format"] == "pack_v2"


def test_junction_created(junction_dir, slide_id, slide_root):
    link = junction_dir / slide_id
    assert link.exists()
    assert _is_reparse_point(link)
    expected = (slide_root / "sample.fastpath").resolve()
    assert link.resolve() == expected
