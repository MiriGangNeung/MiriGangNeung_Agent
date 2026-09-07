"""마감·안전성·재시도 단위 테스트."""

from __future__ import annotations

import io
import pathlib

import pytest
from PIL import Image

from app.core.errors import AiServiceError
from app.pipeline.compose import compose_with_retry
from app.pipeline.finalize import AI_DISCLOSURE, finalize_image
from app.pipeline.prompt import build_composition_prompt
from app.pipeline.safety import check_output, warning_for
from app.places.backgrounds import (
    PlaceContext,
    get_dev_place,
    load_dev_background_image,
    placeholder_background,
    resolve_place_context,
)
from app.providers.base import (
    BackgroundAnalysis,
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

    async def analyze_background(self, image, mime):  # pragma: no cover
        return BackgroundAnalysis()

    async def check_quality(
        self, image, mime, background=None, background_mime=None, subject=None, subject_mime=None
    ):
        self.seen_background = background
        self.seen_subject = subject
        if self._error:
            raise self._error
        return self._verdict


async def test_safety_passes_clean_output():
    status, reason = await check_output(_StubProvider(QualityVerdict(True)), b"x", "image/png")

    assert status is SafetyStatus.PASSED
    assert reason is None


async def test_safety_forwards_background_for_comparison():
    """검사기가 원본 배경을 봐야 간판 글자 변조를 잡을 수 있다."""
    provider = _StubProvider(QualityVerdict(True))

    await check_output(provider, b"result", "image/png", b"background", "image/jpeg")

    assert provider.seen_background == b"background"


async def test_safety_forwards_subject_photo_for_face_comparison():
    """업로드 사진을 넘겨야 '자연스럽지만 남의 얼굴'을 잡을 수 있다."""
    provider = _StubProvider(QualityVerdict(True))

    await check_output(
        provider, b"result", "image/png", b"background", "image/jpeg", b"subject", "image/png"
    )

    assert provider.seen_subject == b"subject"


@pytest.mark.parametrize("reason_code", ["PROPORTION_ERROR", "SCENE_SCALE_BROKEN"])
async def test_safety_rejects_new_v3_failures(reason_code: str):
    """v3 검사판이 새로 잡는 것들은 재시도 없이 거부돼야 한다."""
    provider = _StubProvider(QualityVerdict(False, reason_code))

    with pytest.raises(AiServiceError) as excinfo:
        await check_output(provider, b"x", "image/png", b"bg", "image/png", b"subj", "image/png")

    assert excinfo.value.code == "SAFETY_REJECTED_OUTPUT"
    assert excinfo.value.retryable is False
    # 사용자에게 보일 문구가 사유별로 준비돼 있어야 한다.
    assert "기준을 통과하지 못했습니다" not in excinfo.value.message


async def test_face_mismatch_is_a_warning_not_a_rejection():
    """얼굴이 달라도 결과는 준다.

    얼굴이 화면에서 작게 찍힌 사진은 흔한 여행 사진이라, 그걸 이유로 결과를 아예
    막으면 정상 사용자가 대량으로 거부된다. 경고만 달고 통과시킨다.
    """
    provider = _StubProvider(QualityVerdict(False, "FACE_NOT_PRESERVED"))

    status, reason = await check_output(
        provider, b"x", "image/png", b"bg", "image/png", b"subj", "image/png"
    )

    assert status is SafetyStatus.PASSED
    assert reason == "FACE_NOT_PRESERVED"

    code, message = warning_for(reason)
    assert code == "FACE_NOT_PRESERVED"
    # 결과를 받은 사용자에게 "제공할 수 없습니다"라고 하면 앞뒤가 맞지 않는다.
    assert "제공할 수 없습니다" not in message
    assert "다시 만들어 보세요" in message


async def test_safety_rejects_altered_background():
    provider = _StubProvider(QualityVerdict(False, "BACKGROUND_ALTERED"))

    with pytest.raises(AiServiceError) as excinfo:
        await check_output(provider, b"x", "image/png", b"bg", "image/png")

    assert excinfo.value.code == "SAFETY_REJECTED_OUTPUT"
    assert excinfo.value.retryable is False


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

    async def analyze_background(self, image, mime):  # pragma: no cover
        return BackgroundAnalysis()

    async def check_quality(
        self, image, mime, background=None, background_mime=None, subject=None, subject_mime=None
    ):  # pragma: no cover
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


# ── v5 프롬프트: 인물 크기·의상 ──────────────────────────────


def test_framing_prefers_subject_zone_over_conflicting_half_body():
    """'half-body'와 '화면 높이 25%'는 동시에 성립할 수 없다 — 크기를 명시한 쪽을 따른다.

    실제로 구룡폭포·정동심곡 결과가 zone을 무시하고 반신 크기로 나왔다.
    """
    place = PlaceContext(
        name="구룡폭포(소금강)",
        scene_hint="계곡",
        lighting_hint="흐림",
        suggested_framing="half-body",
        subject_zone="center-left, ~25% of frame height",
    )

    prompt = build_composition_prompt(place, AspectRatio.PORTRAIT, [])

    assert "Frame the result as full-body, small in the frame" in prompt
    assert "Frame the result as half-body" not in prompt


def test_framing_keeps_half_body_when_zone_is_large():
    """충돌이 아닐 때는 VLM 판정을 그대로 둔다."""
    place = PlaceContext(
        name="어딘가",
        scene_hint="장면",
        lighting_hint="빛",
        suggested_framing="half-body",
        subject_zone="center, ~70% of frame height",
    )

    assert "Frame the result as half-body" in build_composition_prompt(
        place, AspectRatio.PORTRAIT, []
    )


def test_composition_prompt_always_carries_outfit_rules():
    """의상 지침이 매칭되지 않은 장소도 '옷을 바꾸지 말라'는 지시는 받아야 한다."""
    place = PlaceContext(name="이름 없는 곳", scene_hint="장면", lighting_hint="빛")

    prompt = build_composition_prompt(place, AspectRatio.PORTRAIT, [])

    assert "{outfit_direction}" not in prompt
    assert "{outfit_negative}" not in prompt
    assert "원본에 없던 옷을 새로 지어내지 않는다" in prompt


def test_outfit_guide_matches_place_absent_from_survey_by_scene_keywords():
    """조사 문서에 없는 장소도 장면 유형 키워드로 규칙이 붙어야 한다.

    문서의 43개 장소는 표본이라, 장소명으로만 색인하면 송정해변·대관령박물관처럼
    실제로 서비스하는 장소가 통째로 빈다.
    """
    from app.places.outfit_guides import get_outfit_scene_type

    assert get_outfit_scene_type(None, "모래사장과 수평선이 보이는 사진").id == "beach"
    assert get_outfit_scene_type(None, "박물관 외관과 전시실").id == "museum"
    # 장소명이 문서에 있으면 키워드보다 우선한다.
    assert get_outfit_scene_type("안반데기", "모래사장").id == "highland"


# ── 얼굴 신원 보존 (regenerate.py, face_identity.py) ──────────


class _ScriptedProvider(ImageCompositionProvider):
    """정해진 순서로 결과를 돌려주고 호출 횟수를 센다."""

    name = "scripted"
    image_model = "scripted-image"
    vision_model = "scripted-vision"

    def __init__(self, images: list[bytes]):
        self._images = list(images)
        self.compose_calls = 0
        self.quality_calls = 0

    async def compose(self, request):
        self.compose_calls += 1
        index = min(self.compose_calls - 1, len(self._images) - 1)
        return CompositionOutput(image=self._images[index], estimated_cost_usd=0.1)

    async def analyze_style(self, image, mime):  # pragma: no cover
        return []

    async def analyze_background(self, image, mime):  # pragma: no cover
        return BackgroundAnalysis()

    async def check_quality(
        self, image, mime, background=None, background_mime=None, subject=None, subject_mime=None
    ):
        self.quality_calls += 1
        return QualityVerdict(True)


async def _regenerate(provider, scores, *, target=0.45, max_attempts=3, monkeypatch=None):
    from app.pipeline import regenerate

    calls = iter(scores)
    monkeypatch.setattr(regenerate, "face_similarity", lambda ref, cand: next(calls))
    return await regenerate.compose_until_face_matches(
        provider,
        _request(),
        reference_image=b"subject",
        timeout_seconds=5.0,
        max_retries=0,
        max_attempts=max_attempts,
        similarity_target=target,
    )


async def test_regeneration_stops_as_soon_as_the_face_matches(monkeypatch):
    provider = _ScriptedProvider([b"a", b"b", b"c"])

    result = await _regenerate(provider, [0.20, 0.80], monkeypatch=monkeypatch)

    assert provider.compose_calls == 2
    assert result.output.image == b"b"
    assert result.similarity == 0.80


async def test_regeneration_returns_the_best_candidate_when_it_never_reaches_target(monkeypatch):
    """상한을 다 써도 예외를 던지지 않고 가장 닮은 결과를 준다.

    사용자에게 결과는 반드시 준다는 것이 정책이다 — 얼굴이 달라도 경고만 단다.
    """
    provider = _ScriptedProvider([b"a", b"b", b"c"])

    result = await _regenerate(provider, [0.20, 0.41, 0.11], monkeypatch=monkeypatch)

    assert provider.compose_calls == 3
    assert result.output.image == b"b"  # 최고점
    assert result.similarity == 0.41


async def test_regeneration_does_not_add_vision_calls(monkeypatch):
    """재생성이 늘리는 것은 이미지 생성뿐이다.

    시도마다 품질 검사를 부르면 작업 시간이 N배가 되어 실서비스에 쓸 수 없다.
    """
    provider = _ScriptedProvider([b"a", b"b", b"c"])

    await _regenerate(provider, [0.10, 0.10, 0.10], monkeypatch=monkeypatch)

    assert provider.compose_calls == 3
    assert provider.quality_calls == 0


async def test_regeneration_gives_up_judging_when_no_face_is_found(monkeypatch):
    """유사도가 None이면 '다른 사람'이 아니라 '판정 불가'다. 재생성하지 않는다."""
    provider = _ScriptedProvider([b"a", b"b"])

    result = await _regenerate(provider, [None], monkeypatch=monkeypatch)

    assert provider.compose_calls == 1
    assert result.similarity is None


def test_face_ratio_is_relative_not_absolute():
    """같은 사진을 확대해도 얼굴 비율은 그대로여야 한다.

    절대 픽셀로 판단하면 고해상도 전신샷이 '얼굴이 크다'고 잘못 분류된다.
    """
    from app.pipeline.face_identity import face_ratio

    original = pathlib.Path("woman1.jpg")
    if not original.is_file():
        pytest.skip("인물 사진이 로컬에만 있어 CI에서는 건너뛴다")

    data = original.read_bytes()
    with Image.open(io.BytesIO(data)) as image:
        doubled = io.BytesIO()
        image.convert("RGB").resize((image.width * 2, image.height * 2)).save(doubled, format="PNG")

    base = face_ratio(data)
    scaled = face_ratio(doubled.getvalue())

    assert base is not None and scaled is not None
    assert abs(base - scaled) < 0.03


def test_face_similarity_is_none_without_a_recognition_model(monkeypatch):
    """인식 모델이 없으면 판정을 건너뛴다 — YuNet→Haar 폴백과 같은 원칙."""
    from app.pipeline import face_identity

    face_identity._recognizer.cache_clear()
    monkeypatch.setattr(face_identity, "_recognizer", lambda: None)

    assert face_identity.face_similarity(b"a", b"b") is None


def test_gemini_no_longer_gates_on_the_vision_face_judgment():
    """`face_matches_subject`는 판정에 쓰지 않고 관측 필드로만 남는다.

    실측에서 이 필드가 SFace 0.587/0.590짜리 결과에도 false를 돌려줬다 — 사람 눈으로
    확인한 '같은 사람' 기준보다 높은 값이다. 신원 판정은 로컬 임베딩이 맡는다.
    """
    import inspect

    from app.providers import gemini

    source = inspect.getsource(gemini.GeminiProvider.check_quality)
    assert "FACE_NOT_PRESERVED" not in source
