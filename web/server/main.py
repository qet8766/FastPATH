from __future__ import annotations

import logging

from fastapi import FastAPI

from .config import ServerConfig, load_config
from .routes.slides import build_slide_index, create_junctions, create_slides_router

logger = logging.getLogger(__name__)


def create_app(config: ServerConfig | None = None) -> FastAPI:
    config = config or load_config()
    slides = build_slide_index(config.slide_dirs)
    create_junctions(slides, config.junction_dir)

    app = FastAPI()
    app.state.config = config
    app.state.slides = slides
    app.include_router(create_slides_router(slides))
    return app


app = create_app()
