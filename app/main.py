"""FastAPI 앱 팩토리."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api import deps, routes_generation, routes_meta
from app.core.config import get_settings
from app.core.errors import AiServiceError
from app.core.logging import configure_logging

logger = logging.getLogger(__name__)

CLEANUP_INTERVAL_SECONDS = 3600


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    runtime = deps.configure(settings)

    cleanup = asyncio.create_task(_cleanup_loop(runtime))
    try:
        yield
    finally:
        cleanup.cancel()
        await asyncio.gather(cleanup, return_exceptions=True)
        await runtime.runner.drain()


async def _cleanup_loop(runtime: deps.Runtime) -> None:
    """만료된 임시 이미지를 주기적으로 지운다 (요구사항 B5, E7)."""
    while True:
        try:
            await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)
            runtime.images.purge_expired()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("임시 이미지 정리 중 오류가 발생했습니다.")


def create_app() -> FastAPI:
    app = FastAPI(
        title="미리강릉 사진 합성 AI",
        description="사용자 사진과 강릉 관광지 배경을 합성하는 비동기 Job 서비스",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.include_router(routes_meta.router)
    app.include_router(routes_generation.router)

    @app.exception_handler(AiServiceError)
    async def handle_service_error(_: Request, exc: AiServiceError) -> JSONResponse:
        return JSONResponse(status_code=exc.http_status, content={"error": exc.to_payload()})

    return app


app = create_app()
