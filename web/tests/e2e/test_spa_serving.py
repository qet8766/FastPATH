"""E2E tests for Caddy fronting SPA + API."""

from __future__ import annotations

import re

from playwright.sync_api import Page, expect


def _extract_asset_path(html: str) -> str:
    match = re.search(r'/(assets/[^"\']+\.(?:js|css))', html)
    if not match:
        raise AssertionError("No asset path found in index.html")
    return match.group(0)


def test_spa_root_loads(page: Page, base_url: str) -> None:
    """GET / serves index.html with the React app shell."""
    page.goto(base_url)
    expect(page).to_have_title("FastPATH Web Viewer")
    expect(page.get_by_role("heading", name="FastPATH")).to_be_visible()
    expect(page.get_by_text("Web Viewer")).to_be_visible()


def test_slide_list_populated(page: Page, base_url: str) -> None:
    """The slide list loads from /api/slides and shows the test slide."""
    page.goto(base_url)
    slide_item = page.get_by_role("listitem")
    expect(slide_item).to_be_visible()
    expect(slide_item).to_contain_text("sample")
    expect(slide_item).to_contain_text("1024")


def test_placeholder_shown_before_selection(page: Page, base_url: str) -> None:
    """Before selecting a slide, a placeholder message is shown."""
    page.goto(base_url)
    expect(page.get_by_text("Select a slide")).to_be_visible()


def test_zoom_controls_visible(page: Page, base_url: str) -> None:
    """Zoom controls (+, -, Fit) are present in the viewer."""
    page.goto(base_url)
    expect(page.get_by_role("button", name="+")).to_be_visible()
    expect(page.get_by_role("button", name=re.compile(r"^−$"))).to_be_visible()
    expect(page.get_by_role("button", name="Fit")).to_be_visible()


def test_vite_assets_served(page: Page, base_url: str) -> None:
    """Hashed JS/CSS bundles under /assets/ are served with correct headers."""
    index_response = page.request.get(base_url)
    asset_path = _extract_asset_path(index_response.text())
    asset_response = page.request.get(f"{base_url}{asset_path}")
    assert asset_response.status == 200
    page.goto(base_url)

    # Check that main JS bundle loaded (it would fail to render otherwise)
    expect(page.get_by_role("heading", name="FastPATH")).to_be_visible()


def test_asset_cache_headers(page: Page, base_url: str) -> None:
    """Vite hashed assets get immutable cache-control headers."""
    index_response = page.request.get(base_url)
    asset_path = _extract_asset_path(index_response.text())
    response = page.request.get(f"{base_url}{asset_path}")
    cache_control = response.headers.get("cache-control", "")
    assert "immutable" in cache_control
    assert "max-age=31536000" in cache_control


def test_api_still_works(page: Page, base_url: str) -> None:
    """/api/slides returns JSON, not index.html."""
    response = page.request.get(f"{base_url}/api/slides")
    assert response.status == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert "hash" in data[0]


def test_api_404_not_swallowed(page: Page, base_url: str) -> None:
    """Requests to /api/... that don't match a route return 404, not index.html."""
    response = page.request.get(f"{base_url}/api/nonexistent")
    assert response.status == 404


def test_slide_file_404_not_swallowed(page: Page, base_url: str) -> None:
    """Requests to /slides/... with bad IDs return 404, not index.html."""
    response = page.request.get(f"{base_url}/slides/bad_id/tiles/level_0.pack")
    assert response.status == 404


def test_slide_pack_range(page: Page, base_url: str, slide_id: str) -> None:
    response = page.request.get(
        f"{base_url}/slides/{slide_id}/tiles/level_0.pack",
        headers={"Range": "bytes=0-3"},
    )
    assert response.status == 206
    assert response.body() == b"tile"
    assert response.headers.get("content-range") == "bytes 0-3/10"


def test_spa_fallback_for_client_routes(page: Page, base_url: str) -> None:
    """Unknown paths return index.html (SPA client-side routing)."""
    page.goto(f"{base_url}/some/client/route")
    expect(page).to_have_title("FastPATH Web Viewer")
    expect(page.get_by_role("heading", name="FastPATH")).to_be_visible()


def test_service_worker_served(page: Page, base_url: str) -> None:
    """/sw.js is served with no-cache header."""
    response = page.request.get(f"{base_url}/sw.js")
    assert response.status == 200
    assert "no-cache" in response.headers.get("cache-control", "")
    assert "skipWaiting" in response.text()


def test_all_requests_single_origin(page: Page, base_url: str) -> None:
    """All network requests during page load go through the same origin."""
    requests: list[str] = []
    page.on("request", lambda req: requests.append(req.url))

    page.goto(base_url)
    # Wait for slide list to load (proves API call completed)
    expect(page.get_by_role("listitem")).to_be_visible()

    # Every request should be to our server
    for url in requests:
        assert url.startswith(base_url), f"Request escaped to external origin: {url}"
