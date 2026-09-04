"""VLM 사전 분석 리포트 로더.

`scripts/analyze_top_places.py`가 오프라인으로 생성해 커밋한
`assets/places/place_insights.json`을 읽는다. 이 파일은 실제 백엔드 `Place.id`
(UUID)를 키로, 그 장소의 Type1(변경 허용) 이미지 각각에 대한 합성용 장면·조명·
카메라·인물 배치 분석을 담는다.

같은 장소라도 사진마다 구도가 다르므로 이미지별 결과를 하나로 합치지 않는다 —
사용자가 프론트에서 특정 사진을 고르면, 백엔드가 그 사진의 원본 URL을 함께
보내오고, 이 서비스는 그 URL로 정확히 그 사진의 분석 데이터를 찾아 합성 프롬프트를
짠다 (`app/places/backgrounds.py::resolve_place_context`).

파일이 없거나 비어 있어도 서비스는 정상 동작해야 한다 — 이 모듈은 항상 빈 결과를
돌려주고, 호출자(`resolve_place_context`)가 다음 우선순위(백엔드 제공 필드 →
범용 문구)로 넘어간다. HF API 등 외부 의존성은 이 모듈에 전혀 없다 — 배치 스크립트
전용이다.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from functools import lru_cache

from app.core.config import get_settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ImageInsight:
    """이미지 한 장에 대한 VLM 합성용 분석 결과."""

    place_id: str
    place_name: str
    source_url: str
    scene_hint: str
    mood_tags: tuple[str, ...] = field(default_factory=tuple)
    notable_features: tuple[str, ...] = field(default_factory=tuple)
    lighting: dict = field(default_factory=dict)
    camera: dict = field(default_factory=dict)
    placement: dict = field(default_factory=dict)
    color_palette: tuple[str, ...] = field(default_factory=tuple)
    season: str = ""
    # 이 사진이 인물 배경으로 쓸 만한지 (high/medium/low). 설 자리가 없는 사진은
    # 배치 스크립트에서 이미 low로 떨어진다.
    portrait_viability: str = ""
    viability_reason: str = ""
    # 인물이 설 수 있는지와 별개로, 배경으로서 매력적인지 (high/medium/low)
    scene_appeal: str = ""
    distractions: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_viable(self) -> bool:
        return self.portrait_viability in ("high", "medium")

    def as_scene_hint(self) -> str:
        """scene_hint + notable_features + mood_tags를 하나의 문장으로 합친다."""
        parts = [self.scene_hint] if self.scene_hint else []
        if self.notable_features:
            parts.append("눈에 띄는 요소: " + ", ".join(self.notable_features))
        if self.mood_tags:
            parts.append("분위기: " + ", ".join(self.mood_tags))
        return " ".join(parts)

    def as_lighting_hint(self) -> str:
        """조명 통제 어휘(lighting dict)를 프롬프트에 넣을 한 줄로 합친다."""
        values = [v for v in self.lighting.values() if v]
        return ", ".join(values)


@lru_cache
def load_place_insights() -> dict[str, list[ImageInsight]]:
    path = get_settings().places_dir / "place_insights.json"
    if not path.is_file():
        return {}

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("place_insights.json을 읽지 못했습니다.")
        return {}

    catalog: dict[str, list[ImageInsight]] = {}
    for entry in raw.get("places", []):
        place_id = entry.get("placeId")
        if not place_id:
            continue
        place_name = entry.get("placeName", "")
        images = [
            ImageInsight(
                place_id=place_id,
                place_name=place_name,
                source_url=image.get("sourceUrl", ""),
                scene_hint=image.get("sceneHint", ""),
                mood_tags=tuple(image.get("moodTags", [])),
                notable_features=tuple(image.get("notableFeatures", [])),
                lighting=image.get("lighting", {}),
                camera=image.get("camera", {}),
                placement=image.get("placement", {}),
                color_palette=tuple(image.get("colorPalette", [])),
                season=image.get("season", ""),
                portrait_viability=image.get("portraitViability", ""),
                viability_reason=image.get("viabilityReason", ""),
                scene_appeal=image.get("sceneAppeal", ""),
                distractions=tuple(image.get("distractions", [])),
            )
            for image in entry.get("images", [])
        ]
        if images:
            catalog[place_id] = images
    return catalog


def _preferred(images: list[ImageInsight]) -> ImageInsight:
    """사진을 특정하지 못했을 때 쓸 대표 이미지.

    인물이 설 자리가 있는(viable) 사진을 우선하고, 그중에서도 high를 먼저 쓴다.
    전부 low면 어쩔 수 없이 첫 번째를 쓴다 — 그 장소에는 쓸 만한 배경이 없다는
    뜻이라, 애초에 프론트에 노출하지 않는 게 맞다.
    """
    order = {"high": 0, "medium": 1}
    return min(images, key=lambda i: order.get(i.portrait_viability, 2))


def get_place_insight(place_id: str) -> ImageInsight | None:
    """장소의 대표 이미지 인사이트.

    특정 사진이 아니라 장소 단위로만 캐시 히트 여부를 확인해야 하는 호출자
    (`has_precomputed_place_context`)나, 어떤 사진이 선택됐는지 알 수 없는
    경우의 폴백으로 쓴다. 정확히 선택된 사진의 데이터가 필요하면
    `get_image_insight`를 쓴다.
    """
    images = load_place_insights().get(place_id)
    return _preferred(images) if images else None


def get_image_insight(place_id: str, image_url: str | None) -> ImageInsight | None:
    """`place_id`의 이미지 중 `image_url`과 정확히 일치하는 분석을 찾는다.

    일치하는 게 없으면(예: 배경 이미지가 사전 분석 대상 상위 N곳에 못 든 경우)
    인물 배경으로 쓸 만한 사진을 우선해 폴백한다 — place_id 자체가 안 맞으면
    `None`. 사용자가 고른 사진이 명시되면 적합도와 무관하게 그 사진을 쓴다(사용자
    선택이 우선이고, 부적합 사진은 애초에 노출하지 않는 것으로 막아야 한다).
    """
    images = load_place_insights().get(place_id)
    if not images:
        return None
    if image_url:
        for image in images:
            if image.source_url == image_url:
                return image
    return _preferred(images)


def viable_images(place_id: str) -> list[ImageInsight]:
    """인물 배경으로 쓸 만한 사진만. 프론트에 노출할 후보를 고르는 용도."""
    return [i for i in load_place_insights().get(place_id, []) if i.is_viable]


__all__ = [
    "ImageInsight",
    "load_place_insights",
    "get_place_insight",
    "get_image_insight",
    "viable_images",
]
