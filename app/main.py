from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.auth import router as auth_router
from app.api.catalog import router as catalog_router
from app.api.pages import STATIC_DIR
from app.api.pages import router as pages_router
from app.api.router import router
from app.api.videos import router as video_router
from app.core.config import get_settings
from app.core.database import engine


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    yield
    await engine.dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(title=settings.app_name, lifespan=lifespan)
    application.include_router(router)
    application.include_router(auth_router)
    application.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    application.include_router(video_router)
    application.include_router(catalog_router)
    application.include_router(pages_router)
    return application


app = create_app()
