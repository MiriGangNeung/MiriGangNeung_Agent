"""헬스체크와 서비스 메타 정보."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import Runtime, get_runtime
from app.core.errors import ERROR_SPECS
from app.core.security import require_api_key
from app.pipeline.prompt import PROMPT_VERSION
from app.pipeline.safety import (
    SAFETY_REASON_MESSAGES,
    WARNING_MESSAGES,
    WARNING_REASON_CODES,
)
from app.schemas.generation import (
    AspectRatio,
    ErrorCodeSpec,
    HealthResponse,
    MetaResponse,
    SafetyReasonSpec,
)

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
        errorCodes=[
            ErrorCodeSpec(
                code=spec.code,
                httpStatus=spec.http_status,
                retryable=spec.retryable,
                message=spec.message,
            )
            for spec in ERROR_SPECS.values()
        ],
        safetyReasonCodes=[
            SafetyReasonSpec(
                code=code,
                # 경고로 나가는 코드는 결과를 받은 사용자에게 보일 문구가 따로 있다.
                message=WARNING_MESSAGES.get(code, message),
                severity="warn" if code in WARNING_REASON_CODES else "reject",
            )
            for code, message in SAFETY_REASON_MESSAGES.items()
        ],
        faceRegenerateMaxAttempts=runtime.settings.face_regenerate_max_attempts,
    )
