from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from progress_api import __version__
from progress_api.api.router import api_router
from progress_api.config import get_settings
from progress_api.db import engine

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    engine.dispose()


app = FastAPI(
    title=settings.app_name,
    version=__version__,
    description="API สำหรับตรวจ Progress งานก่อสร้างจากวิดีโอ 360 องศา",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router, prefix=settings.api_v1_prefix)


@app.get("/health/live", tags=["health"])
def live() -> dict[str, str]:
    return {"status": "ok", "service": "api", "version": __version__}


@app.get("/health/ready", tags=["health"])
def ready() -> dict[str, Any]:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "status": "not_ready",
                "database": "unavailable",
                "error_type": type(exc).__name__,
            },
        ) from exc
    return {"status": "ready", "database": "ok"}


@app.get("/", include_in_schema=False)
def root() -> dict[str, str]:
    return {"name": settings.app_name, "docs": "/docs", "health": "/health/ready"}
