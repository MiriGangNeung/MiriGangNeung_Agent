"""마감·안전성·재시도 단위 테스트."""

from __future__ import annotations

import io

import pytest
from PIL import Image

from app.core.errors import AiServiceError
from app.pipeline.compose import compose_with_retry
from app.pipeline.finalize import AI_DISCLOSURE, finalize_image
from app.pipeline.prompt import build_composition_prompt
from app.pipeline.safety import check_output
from app.places.backgrounds import (
    PlaceContext,
    get_dev_place,
    load_dev_background_image,
    placeholder_background,
    resolve_place_context,
)
from app.providers.base import (
    CompositionOutput,
    CompositionRequest,
    ImageCompositionProvider,
    ProviderFailure,
    ProviderTimeout,
    QualityVerdict,
)
from app.schemas.generation import AspectRatio, SafetyStatus, StyleTag, VariationMode


def _png(width: int, height: int) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (30, 90, 150)).save(buffer, format="PNG")
    return buffer.getvalue()


# ── finalize (E4, E6) ───────────────────────────────────────
@pytest.mark.parametrize(
    ("ratio", "expected"),
    [(AspectRatio.SQUARE, 1.0), (AspectRatio.PORTRAIT, 0.8), (AspectRatio.STORY, 0.5625)],
)
def test_finalize_crops_to_requested_ratio(ratio, expected):
    data, width, height = finalize_image(
        _png(1000, 1000),
        ratio,
        provider="mock",
        model="m",
        prompt_version="v1",
        place_id="anmok-beach",
    )

    assert round(width / height, 3) == round(expected, 3)
    with Image.open(io.BytesIO(data)) as image:
        assert (image.width, image.height) == (width, height)


def test_finalize_embeds_ai_disclosure_metadata():
    data, _, _ = finalize_image(
        _png(800, 1000),
        AspectRatio.PORTRAIT,
        provider="gemini",
        model="gemini-3.1-flash-image",
        prompt_version="v1",
        place_id="gyeongpo-lake",
    )

    with Image.open(io.BytesIO(data)) as image:
        assert image.info["AIGenerated"] == "true"
        assert image.info["Description"] == AI_DISCLOSURE
        assert image.info["AIProvider"] == "gemini"
        assert image.info["AIModel"] == "gemini-3.1-flash-image"
        assert image.info["PromptVersion"] == "v1"
        assert image.info["OnePickPlaceId"] == "gyeongpo-lake"


# ── safety (E5) ─────────────────────────────────────────────
class _StubProvider(ImageCompositionProvider):
    name = "stub"
    image_model = "stub-image"
    vision_model = "stub-vision"

    def __init__(self, verdict=None, error: Exception | None = None):
        self._verdict = verdict
        self._error = error

    async def compose(self, request):  # pragma: no cover - 여기선 쓰지 않는다
        raise NotImplementedError

    async def analyze_style(self, image, mime):  # pragma: no cover
        return []

    async def check_quality(self, image, mime):
        if self._error:
            raise self._error
        return self._verdict


async def test_safety_passes_clean_output():
    status, reason = await check_output(_StubProvider(QualityVerdict(True)), b"x", "image/png")

    assert status is SafetyStatus.PASSED
    assert reason is None


@pytest.mark.parametrize(
    "reason_code",
    ["HARMFUL_CONTENT", "FACE_DISTORTED", "ANATOMY_ERROR", "PERSON_COUNT_MISMATCH"],
)
async def test_safety_rejects_and_never_asks_for_retry(reason_code):
    provider = _StubProvider(QualityVerdict(False, reason_code))

    with pytest.raises(AiServiceError) as excinfo:
        await check_output(provider, b"x", "image/png")

    assert excinfo.value.code == "SAFETY_REJECTED_OUTPUT"
    assert excinfo.value.retryable is False


async def test_safety_checker_failure_does_not_reject_the_result():
    """검사기 장애로 정상 결과를 버리지 않는다. UNKNOWN으로 통과시킨다."""
    provider = _StubProvider(error=RuntimeError("vision down"))

    status, reason = await check_output(provider, b"x", "image/png")

    assert status is SafetyStatus.UNKNOWN
    assert reason is None


# ── compose 재시도 (E8) ─────────────────────────────────────
class _FlakyProvider(ImageCompositionProvider):
    name = "flaky"
    image_model = "flaky-image"
    vision_model = "flaky-vision"

    def __init__(self, failures: int, exc: Exception | None = None):
        self.calls = 0
        self._failures = failures
        self._exc = exc or ProviderTimeout("timeout")

    async def compose(self, request):
        self.calls += 1
        if self.calls <= self._failures:
            raise self._exc
        return CompositionOutput(image=b"ok")

    async def analyze_style(self, image, mime):  # pragma: no cover
        return []

    async def check_quality(self, image, mime):  # pragma: no cover
        return QualityVerdict(True)


def _request() -> CompositionRequest:
    return CompositionRequest(
        person_image=b"p",
        person_mime="image/png",
        background_image=b"b",
        background_mime="image/png",
        prompt="prompt",
        aspect_ratio=AspectRatio.PORTRAIT,
    )


async def test_compose_retries_transient_failures(monkeypatch):
    monkeypatch.setattr("app.pipeline.compose.RETRY_BACKOFF_SECONDS", 0.0)
    provider = _FlakyProvider(failures=2)

    output, attempts = await compose_with_retry(
        provider, _request(), timeout_seconds=5, max_retries=2
    )

    assert output.image == b"ok"
    assert attempts == 3
    assert provider.calls == 3


async def test_compose_gives_up_after_max_retries(monkeypatch):
    monkeypatch.setattr("app.pipeline.compose.RETRY_BACKOFF_SECONDS", 0.0)
    provider = _FlakyProvider(failures=99)

    with pytest.raises(AiServiceError) as excinfo:
        await compose_with_retry(provider, _request(), timeout_seconds=5, max_retries=1)

    assert excinfo.value.code == "PROVIDER_TIMEOUT"
    assert excinfo.value.retryable is True
    assert provider.calls == 2


async def test_compose_does_not_retry_non_retryable_provider_failure(monkeypatch):
    monkeypatch.setattr("app.pipeline.compose.RETRY_BACKOFF_SECONDS", 0.0)
    provider = _FlakyProvider(failures=99, exc=ProviderFailure("bad input", retryable=False))

    with pytest.raises(AiServiceError) as excinfo:
        await compose_with_retry(provider, _request(), timeout_seconds=5, max_retries=3)

    assert excinfo.value.code == "PROVIDER_ERROR"
    assert provider.calls == 1


async def test_provider_safety_block_becomes_non_retryable_error():
    class _BlockedProvider(_FlakyProvider):
        async def compose(self, request):
            self.calls += 1
            return CompositionOutput(
                image=b"", provider_safety_blocked=True, provider_safety_reason="SAFETY"
            )

    provider = _BlockedProvider(failures=0)

    with pytest.raises(AiServiceError) as excinfo:
        await compose_with_retry(provider, _request(), timeout_seconds=5, max_retries=3)

    assert excinfo.value.code == "SAFETY_REJECTED_INPUT"
    assert excinfo.value.retryable is False
    assert provider.calls == 1


# ── 프롬프트 / 배경 카탈로그 ────────────────────────────────
def test_prompt_injects_place_and_ratio():
    place = PlaceContext("안목해변", "동해 바다가 보이는 해변", "맑은 낮의 자연광")
    prompt = build_composition_prompt(place, AspectRatio.STORY, [])

    assert "안목해변" in prompt
    assert "9:16" in prompt
    assert "{place_name}" not in prompt
    assert "{style_direction}" not in prompt


def test_prompt_uses_high_confidence_style_tags_only():
    tags = [
        StyleTag(category="mood", value="감성적", confidence=0.9),
        StyleTag(category="outfit", value="무시될태그", confidence=0.1),
    ]
    place = PlaceContext("안목해변", "동해 바다가 보이는 해변", "맑은 낮의 자연광")

    prompt = build_composition_prompt(place, AspectRatio.SQUARE, tags)

    assert "감성적" in prompt
    assert "무시될태그" not in prompt


def test_prompt_default_variation_mode_has_no_regeneration_language():
    place = PlaceContext("안목해변", "동해 바다가 보이는 해변", "맑은 낮의 자연광")

    prompt = build_composition_prompt(place, AspectRatio.PORTRAIT, [], VariationMode.SAME)

    assert "regeneration request" not in prompt
    assert "{variation_direction}" not in prompt


@pytest.mark.parametrize(
    ("mode", "expected_phrase"),
    [
        (VariationMode.NEW_POSE, "different pose"),
        (VariationMode.NEW_MOOD, "mood and color tone"),
    ],
)
def test_prompt_injects_variation_direction_for_regeneration(mode, expected_phrase):
    """요구사항 E4: 재생성 시 '구도, 스타일만 살짝 조정' 옵션이 프롬프트에 반영돼야 한다."""
    place = PlaceContext("안목해변", "동해 바다가 보이는 해변", "맑은 낮의 자연광")

    prompt = build_composition_prompt(place, AspectRatio.PORTRAIT, [], mode)

    assert "regeneration request" in prompt
    assert expected_phrase in prompt
    assert "{variation_direction}" not in prompt


def test_resolve_place_context_falls_back_to_backend_supplied_fields():
    """백엔드 Place UUID는 개발 카탈로그와 매칭되지 않으므로 backend 필드를 써야 한다."""
    context = resolve_place_context(
        "9c1d4f2e-real-uuid-from-backend",
        place_name="안목해변",
        place_region="강원특별자치도 강릉시",
        place_description="동해 바다와 백사장이 있는 해변",
    )

    assert context.name == "안목해변"
    assert context.scene_hint == "동해 바다와 백사장이 있는 해변"


def test_resolve_place_context_uses_generic_wording_without_any_hint():
    context = resolve_place_context(
        "9c1d4f2e-real-uuid-from-backend",
        place_name=None,
        place_region=None,
        place_description=None,
    )

    assert "강릉" in context.name or "강릉" in context.scene_hint
    assert "{" not in context.scene_hint


def test_dev_catalog_ids_are_unrelated_to_real_place_uuids():
    """요구사항 확인: 개발 카탈로그는 백엔드 Place.id(UUID)와 절대 매칭되지 않아야 한다."""
    place = get_dev_place("arte-museum")

    assert place is not None
    assert place.name == "아르떼뮤지엄 강릉"
    # 라이선스가 확인되지 않았으므로 usable은 항상 false로 고정돼 있어야 한다 (C3).
    assert place.usable is False


def test_dev_background_returns_none_when_unlicensed_or_missing():
    """요구사항 C3: 사용 권한이 불명확한(또는 파일이 없는) 이미지는 절대 반환하지 않는다."""
    assert load_dev_background_image("anmok-beach") is None
    assert load_dev_background_image("no-such-place") is None


def test_placeholder_background_is_a_valid_image():
    data = placeholder_background()

    with Image.open(io.BytesIO(data)) as image:
        assert image.size == (1024, 1280)
        assert image.format == "PNG"
