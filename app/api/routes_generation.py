"""생성 Job API.

계약 상세는 docs/AI_API_CONTRACT.md. 백엔드 AiGenerationClient의
create / getStatus / cancel 이 각각 POST / GET / POST cancel 에 대응한다.
"""

from __future__ import annotations

import hashlib
import logging
import uuid

from fastapi import APIRouter, Depends, File, Form, Request, Response, UploadFile

from app.api.deps import Runtime, get_runtime
from app.core.errors import AiServiceError
from app.core.limits import enforce_daily_budget, enforce_session_rate_limit
from app.core.security import require_api_key
from app.jobs.store import JobRecord
from app.pipeline.preprocess import preprocess_photo
from app.pipeline.prompt import PROMPT_VERSION
from app.pipeline.validate import validate_photo
from app.places.backgrounds import load_dev_background_image, placeholder_background
from app.schemas.generation import AspectRatio, GenerationJobResponse, JobStatus, VariationMode

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/v1/generations", tags=["generations"], dependencies=[Depends(require_api_key)]
)


def _result_url(job_id: str) -> str:
    return f"/v1/generations/{job_id}/result"


def _respond(record: JobRecord) -> GenerationJobResponse:
    return record.to_response(_result_url(record.provider_job_id))


@router.post("", status_code=202, response_model=GenerationJobResponse)
async def create_generation(
    request: Request,
    photo: UploadFile = File(..., description="사용자 사진 (JPG/PNG/WEBP, 최대 10MB)"),
    onePickPlaceId: str = Form(..., description="원픽 관광지 ID (백엔드 Place.id UUID)"),
    aspectRatio: AspectRatio = Form(default=AspectRatio.PORTRAIT),
    variationMode: VariationMode = Form(
        default=VariationMode.SAME,
        description=(
            "요구사항 E4 재생성 옵션 중 '구도, 스타일만 살짝 조정'. same(기본, 동일 요청은 "
            "재사용) | new_pose(다른 구도/포즈) | new_mood(다른 분위기/톤). '다른 배경 선택' "
            "옵션은 onePickPlaceId/background를 바꿔 재요청하면 된다."
        ),
    ),
    background: UploadFile | None = File(
        default=None,
        description=(
            "배경 이미지. 백엔드가 Place.thumbnailUrl/PlaceImage.imageUrl(한국관광공사 "
            "이미지)에서 가져와 전달해야 한다. mock provider가 아니면 사실상 필수."
        ),
    ),
    placeName: str | None = Form(default=None, description="Place.name (프롬프트 힌트)"),
    placeRegion: str | None = Form(default=None, description="Place.region (프롬프트 힌트)"),
    placeDescription: str | None = Form(
        default=None, description="Place.description (프롬프트 힌트)"
    ),
    idempotencyKey: str | None = Form(default=None),
    sessionId: str | None = Form(default=None),
    runtime: Runtime = Depends(get_runtime),
) -> GenerationJobResponse:
    if not onePickPlaceId.strip():
        raise AiServiceError("INVALID_REQUEST", "onePickPlaceId는 필수입니다.")

    data = await photo.read()
    if not data:
        raise AiServiceError("INVALID_REQUEST", "사진 파일이 비어 있습니다.")

    # 동일 요청 재생성 차단 (검토 총평 §2-7). 명시적 키가 없으면 입력 해시로 만든다.
    # variationMode도 키에 포함해, 백엔드가 idempotencyKey를 따로 관리하지 않아도
    # '구도/분위기 조정' 재생성(E4)이 자동으로 새 Job이 되도록 한다.
    dedupe_key = idempotencyKey or _auto_idempotency_key(
        data, onePickPlaceId, aspectRatio, variationMode
    )
    existing_id = runtime.store.find_by_idempotency_key(dedupe_key)
    if existing_id:
        existing = runtime.store.get(existing_id)
        if existing is not None:
            logger.info("동일 요청이라 기존 Job을 반환합니다.")
            return _respond(existing)

    session = sessionId or (request.client.host if request.client else "")
    enforce_session_rate_limit(
        runtime.store, session, runtime.settings.rate_limit_per_session_per_hour
    )
    enforce_daily_budget(runtime.store, runtime.settings.daily_generation_budget)

    # 요구사항 B4: 부적절한 사진은 분석 전에 차단하고 즉시 안내한다.
    # 따라서 검증(B3/B4)과 전처리(B5)는 Job을 만들기 전에 동기로 처리한다.
    validate_photo(
        data,
        photo.content_type,
        max_bytes=runtime.settings.max_upload_bytes,
        max_pixels=runtime.settings.max_image_pixels,
    )
    clean_bytes, _ = preprocess_photo(data)

    # 배경도 사진과 마찬가지로 Job을 만들기 전에 동기로 해석·검증한다. 실제 배경이
    # 하나도 없는 채로 Job을 만들면 COMPOSITING 단계에서야 실패가 드러나 사용자
    # 대기시간과 비용만 낭비하게 된다.
    background_bytes, background_source = await _resolve_background(
        background, onePickPlaceId, runtime
    )

    record = JobRecord(
        provider_job_id=uuid.uuid4().hex,
        one_pick_place_id=onePickPlaceId.strip(),
        aspect_ratio=aspectRatio,
        variation_mode=variationMode,
        provider=runtime.provider.name,
        model=runtime.provider.image_model,
        prompt_version=PROMPT_VERSION,
        place_name=placeName,
        place_region=placeRegion,
        place_description=placeDescription,
        input_key=runtime.images.save_input(clean_bytes, ".png"),
        background_key=runtime.images.save_input(background_bytes, ".png"),
        idempotency_key=dedupe_key,
        status=JobStatus.QUEUED,
        # 요청 접수 시점에 근사 비용을 미리 채운다 (검토 총평 §2-7). 합성이 끝나면
        # runner.py가 provider가 실제로 돌려준 값으로 다시 덮어쓴다.
        estimated_cost_usd=runtime.provider.estimated_cost_usd,
    )
    logger.info("배경 이미지 출처: %s", background_source)

    runtime.store.save(record)
    runtime.store.remember_idempotency_key(dedupe_key, record.provider_job_id)
    runtime.runner.schedule(record)

    return _respond(record)


@router.get("/{provider_job_id}", response_model=GenerationJobResponse)
async def get_generation(
    provider_job_id: str, runtime: Runtime = Depends(get_runtime)
) -> GenerationJobResponse:
    record = runtime.store.get(provider_job_id)
    if record is None:
        raise AiServiceError("JOB_NOT_FOUND")
    return _respond(record)


@router.get("/{provider_job_id}/result")
async def download_result(
    provider_job_id: str, runtime: Runtime = Depends(get_runtime)
) -> Response:
    record = runtime.store.get(provider_job_id)
    if record is None:
        raise AiServiceError("JOB_NOT_FOUND")
    if record.status is not JobStatus.DONE or not record.result_key:
        raise AiServiceError("JOB_NOT_READY")
    if not runtime.images.result_exists(record.result_key):
        # TTL 정리로 파일이 이미 사라진 경우 (요구사항 E7)
        raise AiServiceError("RESULT_EXPIRED")

    return Response(
        content=runtime.images.read_result(record.result_key),
        media_type="image/png",
        headers={
            "Content-Disposition": f'attachment; filename="composition-{provider_job_id}.png"',
            "Cache-Control": "no-store",
            "X-AI-Generated": "true",
        },
    )


@router.post("/{provider_job_id}/cancel", response_model=GenerationJobResponse)
async def cancel_generation(
    provider_job_id: str, runtime: Runtime = Depends(get_runtime)
) -> GenerationJobResponse:
    record = runtime.store.get(provider_job_id)
    if record is None:
        raise AiServiceError("JOB_NOT_FOUND")
    if record.status.is_terminal:
        return _respond(record)

    record.cancelled = True
    runtime.store.save(record)
    logger.info("Job 취소가 요청되었습니다.")
    return _respond(record)


def _auto_idempotency_key(
    data: bytes,
    one_pick_place_id: str,
    aspect_ratio: AspectRatio,
    variation_mode: VariationMode,
) -> str:
    """입력 사진 + 장소 + 비율 + 변형모드가 같으면 같은 요청으로 본다.

    사용자가 '다시 생성하기(변형 없음)'를 연타해도 동일 조건이면 새로 생성하지 않는다.
    variationMode를 new_pose/new_mood로 바꿔 보내면 자동으로 새 Job이 된다(E4).
    """
    digest = hashlib.sha256(data).hexdigest()
    return f"{digest}:{one_pick_place_id}:{aspect_ratio.value}:{variation_mode.value}"


async def _resolve_background(
    background: UploadFile | None, one_pick_place_id: str, runtime: Runtime
) -> tuple[bytes, str]:
    """(배경 바이트, 출처 설명)을 돌려주거나 실제 배경이 없으면 오류를 던진다.

    우선순위: 백엔드가 업로드한 실제 파일 > 개발용 카탈로그(usable=true인 항목만,
    로컬 개발·수동 테스트 전용) > mock provider의 플레이스홀더. 그 외에는
    `BACKGROUND_REQUIRED` — 특히 `AI_PROVIDER=gemini`에서 실제 배경 없이 조용히
    가짜 그라디언트로 합성해버리는 것을 막기 위함이다.
    """
    if background is not None:
        data = await background.read()
        if data:
            if len(data) > runtime.settings.max_upload_bytes:
                raise AiServiceError(
                    "IMAGE_TOO_LARGE", "배경 이미지 용량이 허용 범위를 넘었습니다."
                )
            return data, "backend-upload"

    dev_match = load_dev_background_image(one_pick_place_id)
    if dev_match is not None:
        data, _ = dev_match
        return data, "dev-catalog"

    if runtime.provider.name == "mock":
        return placeholder_background(), "mock-placeholder"

    raise AiServiceError("BACKGROUND_REQUIRED")
