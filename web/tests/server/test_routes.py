from __future__ import annotations


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


def test_static_pack_headers(client, slide_id):
    response = client.get(f"/slides/{slide_id}/tiles/level_0.pack")
    assert response.status_code == 200
    assert response.headers.get("accept-ranges") == "bytes"
    assert "immutable" in response.headers.get("cache-control", "")
    assert response.headers.get("content-type", "").startswith("application/octet-stream")


def test_static_pack_range(client, slide_id):
    response = client.get(
        f"/slides/{slide_id}/tiles/level_0.pack",
        headers={"Range": "bytes=0-3"},
    )
    assert response.status_code == 206
    assert response.content == b"tile"
    assert response.headers.get("content-range") == "bytes 0-3/10"


def test_static_pack_range_invalid(client, slide_id):
    response = client.get(
        f"/slides/{slide_id}/tiles/level_0.pack",
        headers={"Range": "bytes=100-200"},
    )
    assert response.status_code == 416


def test_path_traversal_denied(client, slide_id):
    response = client.get(f"/slides/{slide_id}/../metadata.json")
    assert response.status_code == 404
