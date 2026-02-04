from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from .config import ServerConfig, load_config
from .routes.slides import SlideRecord, build_slide_index, create_slides_router
from .static_files import build_file_response

logger = logging.getLogger(__name__)


def _resolve_slide_file(slide: SlideRecord, relative_path: str) -> Path:
    candidate = (slide.dir_path / relative_path).resolve()
    try:
        candidate.relative_to(slide.dir_path.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="File not found") from exc
    if not candidate.exists() or not candidate.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return candidate


def create_app(config: ServerConfig | None = None) -> FastAPI:
    config = config or load_config()
    slides = build_slide_index(config.slide_dirs)

    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.config = config
    app.state.slides = slides

    app.include_router(create_slides_router(slides))

    @app.get("/slides/{slide_id}/{file_path:path}")
    def get_slide_file(slide_id: str, file_path: str, request: Request):
        slide = slides.get(slide_id)
        if not slide:
            raise HTTPException(status_code=404, detail="Slide not found")
        path = _resolve_slide_file(slide, file_path)
        return build_file_response(path, request)

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
