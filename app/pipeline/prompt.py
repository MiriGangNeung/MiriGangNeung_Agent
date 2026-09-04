"""프롬프트 조립 + promptVersion 관리.

프롬프트 본문은 `prompts/*.md`에 두고 코드에 하드코딩하지 않는다. 백엔드는
`metadata.promptVersion`만 기록하면 되고(09_AI_INTEGRATION.md), 버전 올림은 여기서
파일을 추가하고 PROMPT_VERSION을 바꾸는 것으로 끝난다.
"""

from __future__ import annotations

import re
from functools import lru_cache

from app.core.config import get_settings
from app.places.backgrounds import PlaceContext
from app.schemas.generation import AspectRatio, StyleTag, VariationMode

PROMPT_VERSION = "v5"

COMPOSITION_TEMPLATE = "composition_v5.md"
QUALITY_CHECK_TEMPLATE = "quality_check_v1.md"
# 원본 배경을 함께 넘길 수 있을 때 쓰는 판. 배경 보존까지 비교한다.
QUALITY_CHECK_WITH_BACKGROUND_TEMPLATE = "quality_check_v2.md"
# 업로드 인물 사진까지 넘길 수 있을 때 쓰는 판. 얼굴 보존·신체 비율까지 본다.
QUALITY_CHECK_WITH_SUBJECT_TEMPLATE = "quality_check_v3.md"
STYLE_ANALYSIS_TEMPLATE = "style_analysis_v1.md"
BACKGROUND_ANALYSIS_TEMPLATE = "background_analysis_v1.md"

_FRONT_MATTER = re.compile(r"^---\n.*?\n---\n", re.DOTALL)


@lru_cache
def load_template(name: str) -> str:
    path = get_settings().prompts_dir / name
    text = path.read_text(encoding="utf-8")
    return _FRONT_MATTER.sub("", text).strip()


def build_composition_prompt(
    place: PlaceContext,
    aspect_ratio: AspectRatio,
    style_tags: list[StyleTag],
    variation_mode: VariationMode = VariationMode.SAME,
) -> str:
    template = load_template(COMPOSITION_TEMPLATE)
    occluding = place.occluding_elements or "nothing"
    # 조사 문서에 없는 장소는 이 두 칸이 비고, 프롬프트는 아래 일반 포즈 지시만 쓴다.
    pose_direction = place.pose_direction or (
        "이 장소에 대한 별도 촬영 지침은 없다. 아래 일반 지침을 따른다."
    )
    pose_negative = (
        f"이 장소에서 특히 피할 것: {place.pose_negative}" if place.pose_negative else ""
    )
    return (
        template.replace("{suggested_framing}", _framing(place))
        .replace("{place_pose_direction}", pose_direction)
        .replace("{place_pose_negative}", pose_negative)
        .replace("{place_name}", place.name)
        .replace("{scene_hint}", place.scene_hint)
        .replace("{lighting_hint}", place.lighting_hint)
        .replace("{time_of_day}", place.time_of_day)
        .replace("{light_direction}", place.light_direction)
        .replace("{light_angle}", place.light_angle)
        .replace("{color_temperature}", place.color_temperature)
        .replace("{shadow_hardness}", place.shadow_hardness)
        .replace("{camera_perspective}", place.camera_perspective)
        .replace("{horizon_position}", place.horizon_position)
        .replace("{ground_plane}", place.ground_plane)
        .replace("{subject_zone}", place.subject_zone)
        .replace("{occluding_elements}", occluding)
        .replace("{outfit_direction}", place.outfit_direction or _DEFAULT_OUTFIT)
        .replace("{outfit_negative}", place.outfit_negative)
        .replace("{mood_tags}", place.mood_tags)
        .replace("{color_palette}", place.color_palette)
        .replace("{style_direction}", _style_direction(style_tags))
        .replace("{aspect_ratio}", aspect_ratio.value)
        .replace("{variation_direction}", _variation_direction(variation_mode))
    )


def build_style_analysis_prompt() -> str:
    return load_template(STYLE_ANALYSIS_TEMPLATE)


def build_background_analysis_prompt() -> str:
    return load_template(BACKGROUND_ANALYSIS_TEMPLATE)


def build_quality_check_prompt(
    with_background: bool = False, with_subject: bool = False
) -> str:
    """품질 검사 프롬프트. 함께 넘길 수 있는 참조 이미지 수에 따라 판이 다르다.

    인물 사진은 배경과 함께일 때만 쓴다 — 프롬프트가 이미지 순서로 역할을
    구분하므로, 배경을 빼고 인물만 두 번째로 넘기면 검사기가 그것을 배경으로
    읽는다.
    """
    if with_background and with_subject:
        return load_template(QUALITY_CHECK_WITH_SUBJECT_TEMPLATE)
    if with_background:
        return load_template(QUALITY_CHECK_WITH_BACKGROUND_TEMPLATE)
    return load_template(QUALITY_CHECK_TEMPLATE)


# 의상 지침이 매칭되지 않은 장소에 쓰는 기본 문구. 옷을 바꾸지 말라는 것만 말한다.
_DEFAULT_OUTFIT = (
    "이 장소에 대한 별도 의상 지침은 없다. 첨부 인물 사진의 상의·하의·신발·"
    "가방·안경을 그대로 유지하고, 원본에 없던 옷을 새로 지어내지 않는다."
)

# 팀 조사 지침이 인물 크기·구도를 이미 지정했는지 판별하는 표현들.
_FRAMING_TERMS = ("전신", "반신", "중경", "클로즈업", "퍼센트", "%")

# suggestedSubjectZone 안의 "~25% of frame height" 같은 표기.
_ZONE_HEIGHT = re.compile(r"~?\s*(\d{1,3})\s*%")

# 이 비율 이하면 인물이 화면에서 작다는 뜻이라, half-body 프레이밍과 양립하지 않는다.
_FULL_BODY_ZONE_MAX = 50


def _framing(place: PlaceContext) -> str:
    """프레이밍 지시. 장소 지침이 이미 정했으면 VLM 판정을 쓰지 않는다.

    조사 문서가 "전신 와이드로 화면 높이의 25~35퍼센트"라고 지정했는데 VLM이 같은
    사진을 `half-body`로 판정한 사례가 있었다. 두 지시를 나란히 넣으면 모델이
    충돌 속에서 임의로 하나를 고른다(실제로 반신이 나왔다). 사람이 장소를 보고
    쓴 지침이 사진 한 장만 본 판정보다 신뢰도가 높으므로 그쪽을 따른다.

    조사 지침이 없어도 같은 충돌이 VLM 판정 내부에서 일어난다. `suggestedFraming`
    이 half-body인데 `suggestedSubjectZone`은 "~25% of frame height"인 사진이
    사용 가능한 것만 12장 있다 — 화면 높이의 4분의 1이면 전신이 작게 들어간다는
    뜻이라 반신 프레이밍과 동시에 성립할 수 없다. 실제로 구룡폭포·정동심곡 결과가
    zone을 무시하고 반신 크기로 나왔다. 두 값이 충돌하면 크기를 명시한 zone을
    믿는다 — 그쪽이 이 사진에서 인물을 어디에 얼마만큼 넣을지 실제로 재본 값이다.
    """
    if any(term in place.pose_direction for term in _FRAMING_TERMS):
        return "exactly as the place guidance above specifies"

    match = _ZONE_HEIGHT.search(place.subject_zone)
    if (
        match
        and int(match.group(1)) <= _FULL_BODY_ZONE_MAX
        and "half" in place.suggested_framing.lower()
    ):
        return "full-body, small in the frame — the subject zone below sets the exact size"
    return place.suggested_framing


def _style_direction(style_tags: list[StyleTag]) -> str:
    """B6 분석 결과를 프롬프트 한 문단으로 녹인다. 신뢰도가 낮은 태그는 버린다."""
    usable = [tag for tag in style_tags if tag.confidence >= 0.4]
    if not usable:
        return (
            "Keep the photographic mood of the original portrait. "
            "Aim for a natural travel-snapshot look."
        )

    parts = ", ".join(f"{tag.category}: {tag.value}" for tag in usable)
    return (
        "The subject's photo reads as — "
        f"{parts}. "
        "Keep the composited result consistent with that mood and outfit."
    )


def _variation_direction(mode: VariationMode) -> str:
    """요구사항 E4 재생성 옵션 중 '구도, 스타일만 살짝 조정'을 프롬프트로 옮긴다.

    '다른 배경 선택' 옵션은 onePickPlaceId/background를 바꿔 재요청하면 되므로 별도
    처리가 필요 없다.
    """
    if mode is VariationMode.NEW_POSE:
        return (
            "This is a regeneration request. Use a noticeably different pose, body "
            "angle and framing than a plain straight-on portrait — for example a "
            "three-quarter turn, a walking pose, or looking off to the side — while "
            "keeping the same person and the same background location."
        )
    if mode is VariationMode.NEW_MOOD:
        return (
            "This is a regeneration request. Shift the photographic mood and color "
            "tone noticeably from a plain snapshot — for example warmer or cooler "
            "light, different time-of-day feel, or higher/lower contrast — while "
            "keeping the same person, the same general pose, and the same background "
            "location."
        )
    return "Keep the composition natural and typical for a travel snapshot at this location."
