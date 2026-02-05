from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.gzip import GZipMiddleware
from starlette.staticfiles import StaticFiles

from .config import ServerConfig, load_config
from .routes.slides import SlideRecord, build_slide_index, create_slides_router
from .static_files import build_file_response

logger = logging.getLogger(__name__)

_DEFAULT_DIST_DIR = Path(__file__).parent.parent / "client" / "dist"


def _resolve_slide_file(slide: SlideRecord, relative_path: str) -> Path:
    candidate = (slide.dir_path / relative_path).resolve()
    try:
        candidate.relative_to(slide.dir_path.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="File not found") from exc
    if not candidate.exists() or not candidate.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return candidate


class _AssetCacheMiddleware(BaseHTTPMiddleware):
    """Set immutable cache headers for Vite hashed asset paths."""

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        response = await call_next(request)
        if request.url.path.startswith("/assets/"):
            response.headers["Cache-Control"] = (
                "public, max-age=31536000, immutable"
            )
        return response


def _get_dist_dir() -> Path | None:
    override = os.getenv("FASTPATH_WEB_DIST_DIR")
    if override:
        p = Path(override)
        if p.is_dir():
            return p
        logger.warning("FASTPATH_WEB_DIST_DIR=%s is not a directory, ignoring", override)
    if _DEFAULT_DIST_DIR.is_dir():
        return _DEFAULT_DIST_DIR
    return None


def create_app(config: ServerConfig | None = None) -> FastAPI:
    config = config or load_config()
    slides = build_slide_index(config.slide_dirs)

    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Content-Range", "Accept-Ranges", "Content-Length"],
    )
    app.add_middleware(GZipMiddleware, minimum_size=500)
    app.state.config = config
    app.state.slides = slides

    # --- API and slide-file routes (highest priority) ---
    app.include_router(create_slides_router(slides))

    @app.api_route("/slides/{slide_id}/{file_path:path}", methods=["GET", "HEAD"])
    def get_slide_file(slide_id: str, file_path: str, request: Request):
        slide = slides.get(slide_id)
        if not slide:
            raise HTTPException(status_code=404, detail="Slide not found")
        path = _resolve_slide_file(slide, file_path)
        return build_file_response(path, request)

    # --- SPA static serving (lower priority, only if dist exists) ---
    dist_dir = _get_dist_dir()
    if dist_dir is None:
        logger.warning(
            "Vite dist directory not found (%s). "
            "SPA will not be served. Run 'npm run build' in web/client/ first.",
            _DEFAULT_DIST_DIR,
        )
    else:
        logger.info("Serving SPA from %s", dist_dir)
        app.add_middleware(_AssetCacheMiddleware)

        # Mount /assets as static files (Vite hashed bundles)
        assets_dir = dist_dir / "assets"
        if assets_dir.is_dir():
            app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

        # Read index.html once at startup
        index_html = (dist_dir / "index.html").read_text(encoding="utf-8")

        @app.get("/sw.js", include_in_schema=False)
        def service_worker():
            sw_path = dist_dir / "sw.js"
            if not sw_path.exists():
                raise HTTPException(status_code=404, detail="Not found")
            return HTMLResponse(
                content=sw_path.read_text(encoding="utf-8"),
                media_type="application/javascript",
                headers={"Cache-Control": "no-cache"},
            )

        @app.get("/{full_path:path}", include_in_schema=False)
        def spa_fallback(full_path: str):
            # Don't serve index.html for API or slide-data paths that
            # fell through — those should 404 properly.
            if full_path.startswith(("api/", "slides/")):
                raise HTTPException(status_code=404, detail="Not found")
            return HTMLResponse(content=index_html)

    return app


app = create_app()


def main() -> None:
    import uvicorn

    config = load_config()
    uvicorn.run(
        "web.server.main:app",
        host=config.host,
        port=config.port,
        reload=True,
    )


if __name__ == "__main__":
    main()
