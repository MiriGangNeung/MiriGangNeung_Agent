"""Google Gemini 프로바이더.

google-genai 2.x 기준으로 검증한 호출 형태:
    client.aio.models.generate_content(
        model="gemini-3.1-flash-image",
        contents=[Part.from_bytes(...), Part.from_bytes(...), "prompt"],
        config=GenerateContentConfig(
            response_modalities=["IMAGE"],
            image_config=ImageConfig(aspect_ratio="4:5"),
        ),
    )

결과 이미지에는 SynthID 워터마크가 자동으로 들어간다 (요구사항 E6).
"""

from __future__ import annotations

import json
import logging
import re

from google import genai
from google.genai import types

from app.core.config import Settings
from app.pipeline.prompt import (
    build_background_analysis_prompt,
    build_quality_check_prompt,
    build_style_analysis_prompt,
)
from app.providers.base import (
    BackgroundAnalysis,
    CompositionOutput,
    CompositionRequest,
    ImageCompositionProvider,
    ProviderFailure,
    QualityVerdict,
)
from app.schemas.generation import StyleTag

logger = logging.getLogger(__name__)

# 입력 안전성으로 막힌 경우 (재시도 금지 대상)
_SAFETY_FINISH_REASONS = frozenset(
    {
        "SAFETY",
        "PROHIBITED_CONTENT",
        "IMAGE_SAFETY",
        "IMAGE_PROHIBITED_CONTENT",
        "BLOCKLIST",
        "SPII",
    }
)

# 1K 출력 기준 개략 단가. 정확한 정산이 아니라 단위경제성 추적용 근사치다.
_APPROX_COST_PER_IMAGE_USD = {
    "gemini-3.1-flash-lite-image": 0.045,
    "gemini-3.1-flash-image": 0.067,
    "gemini-3-pro-image": 0.134,
    "gemini-2.5-flash-image": 0.039,
}

_JSON_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


class GeminiProvider(ImageCompositionProvider):
    name = "gemini"

    def __init__(self, settings: Settings):
        self._client = genai.Client(api_key=settings.google_api_key)
        self.image_model = settings.gemini_image_model
        self.vision_model = settings.gemini_vision_model

    @property
    def estimated_cost_usd(self) -> float | None:
        return _APPROX_COST_PER_IMAGE_USD.get(self.image_model)

    # ── 합성 (E1~E4) ────────────────────────────────────────
    async def compose(self, request: CompositionRequest) -> CompositionOutput:
        contents = [
            types.Part.from_bytes(data=request.person_image, mime_type=request.person_mime),
            types.Part.from_bytes(data=request.background_image, mime_type=request.background_mime),
            request.prompt,
        ]
        config = types.GenerateContentConfig(
            response_modalities=["IMAGE"],
            image_config=types.ImageConfig(aspect_ratio=request.aspect_ratio.value),
        )

        try:
            response = await self._client.aio.models.generate_content(
                model=self.image_model, contents=contents, config=config
            )
        except Exception as exc:  # noqa: BLE001 - SDK 예외를 어댑터 예외로 번역
            raise ProviderFailure(
                f"Gemini 호출 실패: {type(exc).__name__}", retryable=True
            ) from exc

        blocked, reason = _safety_block(response)
        if blocked:
            return CompositionOutput(
                image=b"",
                provider_safety_blocked=True,
                provider_safety_reason=reason,
            )

        image_bytes, mime = _first_image(response)
        if image_bytes is None:
            # 이미지가 없는데 안전성 사유도 아니면 일시적 실패로 보고 재시도한다.
            raise ProviderFailure("Gemini 응답에 이미지가 없습니다.", retryable=True)

        return CompositionOutput(
            image=image_bytes,
            mime=mime,
            estimated_cost_usd=self.estimated_cost_usd,
        )

    # ── 스타일 분석 (B6) ────────────────────────────────────
    async def analyze_style(self, image: bytes, mime: str) -> list[StyleTag]:
        payload = await self._ask_json(image, mime, build_style_analysis_prompt())
        tags: list[StyleTag] = []
        for entry in payload.get("tags", []):
            try:
                tags.append(
                    StyleTag(
                        category=str(entry["category"]),
                        value=str(entry["value"]),
                        confidence=max(0.0, min(1.0, float(entry["confidence"]))),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        return tags

    # ── 배경 이미지 실시간 분석 (docs/adr/0004-realtime-background-analysis.md) ──
    async def analyze_background(self, image: bytes, mime: str) -> BackgroundAnalysis:
        payload = await self._ask_json(image, mime, build_background_analysis_prompt())
        return BackgroundAnalysis(
            scene_description=str(payload.get("scene_description", "")),
            lighting=str(payload.get("lighting", "")),
            notable_features=tuple(str(v) for v in payload.get("notable_features", []) if v),
            mood_tags=tuple(str(v) for v in payload.get("mood_tags", []) if v),
        )

    # ── 품질·안전성 검사 (E5) ───────────────────────────────
    async def check_quality(self, image: bytes, mime: str) -> QualityVerdict:
        payload = await self._ask_json(image, mime, build_quality_check_prompt())

        if payload.get("harmful_content") is True:
            return QualityVerdict(False, "HARMFUL_CONTENT", payload)
        if payload.get("face_natural") is False:
            return QualityVerdict(False, "FACE_DISTORTED", payload)
        if payload.get("anatomy_correct") is False:
            return QualityVerdict(False, "ANATOMY_ERROR", payload)
        if payload.get("severe_artifacts") is True:
            return QualityVerdict(False, "SEVERE_ARTIFACTS", payload)

        person_count = payload.get("person_count")
        if isinstance(person_count, int) and person_count != 1:
            return QualityVerdict(False, "PERSON_COUNT_MISMATCH", payload)

        return QualityVerdict(True, None, payload)

    async def _ask_json(self, image: bytes, mime: str, prompt: str) -> dict:
        try:
            response = await self._client.aio.models.generate_content(
                model=self.vision_model,
                contents=[types.Part.from_bytes(data=image, mime_type=mime), prompt],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json", temperature=0.0
                ),
            )
        except Exception as exc:  # noqa: BLE001
            raise ProviderFailure(
                f"Gemini vision 호출 실패: {type(exc).__name__}", retryable=True
            ) from exc

        text = (response.text or "").strip()
        if not text:
            return {}
        try:
            return json.loads(_JSON_FENCE.sub("", text).strip())
        except json.JSONDecodeError:
            logger.warning("Gemini vision 응답을 JSON으로 파싱하지 못했습니다.")
            return {}


def _safety_block(response: types.GenerateContentResponse) -> tuple[bool, str | None]:
    feedback = getattr(response, "prompt_feedback", None)
    block_reason = getattr(feedback, "block_reason", None) if feedback else None
    if block_reason is not None:
        return True, _enum_name(block_reason)

    for candidate in response.candidates or []:
        finish = _enum_name(getattr(candidate, "finish_reason", None))
        if finish in _SAFETY_FINISH_REASONS:
            return True, finish
    return False, None


def _first_image(response: types.GenerateContentResponse) -> tuple[bytes | None, str]:
    for candidate in response.candidates or []:
        content = getattr(candidate, "content", None)
        for part in getattr(content, "parts", None) or []:
            inline = getattr(part, "inline_data", None)
            if inline is not None and inline.data:
                return inline.data, inline.mime_type or "image/png"
    return None, "image/png"


def _enum_name(value: object) -> str | None:
    if value is None:
        return None
    return getattr(value, "name", None) or str(value)
