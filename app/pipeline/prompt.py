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
from app.schemas.generation import AspectRatio, StyleTag

PROMPT_VERSION = "v1"

COMPOSITION_TEMPLATE = "composition_v1.md"
QUALITY_CHECK_TEMPLATE = "quality_check_v1.md"
STYLE_ANALYSIS_TEMPLATE = "style_analysis_v1.md"

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
) -> str:
    template = load_template(COMPOSITION_TEMPLATE)
    return (
        template.replace("{place_name}", place.name)
        .replace("{scene_hint}", place.scene_hint)
        .replace("{lighting_hint}", place.lighting_hint)
        .replace("{style_direction}", _style_direction(style_tags))
        .replace("{aspect_ratio}", aspect_ratio.value)
    )


def build_style_analysis_prompt() -> str:
    return load_template(STYLE_ANALYSIS_TEMPLATE)


def build_quality_check_prompt() -> str:
    return load_template(QUALITY_CHECK_TEMPLATE)


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
