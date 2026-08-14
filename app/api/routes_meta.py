"""헬스체크와 서비스 메타 정보."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import Runtime, get_runtime
from app.core.security import require_api_key
from app.pipeline.prompt import PROMPT_VERSION
from app.schemas.generation import AspectRatio, HealthResponse, MetaResponse

router = APIRouter(tags=["meta"])


@router.get("/health", response_model=HealthResponse)
async def health(runtime: Runtime = Depends(get_runtime)) -> HealthResponse:
    return HealthResponse(status="ok", jobStore=runtime.store.name, provider=runtime.provider.name)


@router.get("/v1/meta", response_model=MetaResponse, dependencies=[Depends(require_api_key)])
async def meta(runtime: Runtime = Depends(get_runtime)) -> MetaResponse:
    return MetaResponse(
        provider=runtime.provider.name,
        imageModel=runtime.provider.image_model,
        visionModel=runtime.provider.vision_model,
        promptVersion=PROMPT_VERSION,
        supportedAspectRatios=list(AspectRatio),
        maxUploadBytes=runtime.settings.max_upload_bytes,
        resultTtlSeconds=runtime.settings.result_ttl_seconds,
    )
