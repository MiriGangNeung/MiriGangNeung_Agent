"""VLM 사전 분석 리포트 로더.

`scripts/analyze_top_places.py`가 오프라인으로 생성해 커밋한
`assets/places/place_insights.json`을 읽는다. 이 파일은 실제 백엔드 `Place.id`
(UUID)를 키로 하는, Type1(변경 허용) 이미지만 분석한 상위 N개 장소의 장면·조명·분위기
리포트다.

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
class PlaceInsight:
    place_id: str
    place_name: str
    scene_hint: str
    lighting_hint: str
    mood_tags: tuple[str, ...] = field(default_factory=tuple)
    notable_features: tuple[str, ...] = field(default_factory=tuple)

    def as_scene_hint(self) -> str:
        """scene_hint + notable_features + mood_tags를 하나의 문장으로 합친다.

        PlaceContext/프롬프트 템플릿 스키마는 그대로 두고(3필드 유지), 문자열
        내용만 더 풍부하게 만드는 최소 diff 방향.
        """
        parts = [self.scene_hint] if self.scene_hint else []
        if self.notable_features:
            parts.append("눈에 띄는 요소: " + ", ".join(self.notable_features))
        if self.mood_tags:
            parts.append("분위기: " + ", ".join(self.mood_tags))
        return " ".join(parts)


@lru_cache
def load_place_insights() -> dict[str, PlaceInsight]:
    path = get_settings().places_dir / "place_insights.json"
    if not path.is_file():
        return {}

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("place_insights.json을 읽지 못했습니다.")
        return {}

    catalog: dict[str, PlaceInsight] = {}
    for entry in raw.get("places", []):
        place_id = entry.get("placeId")
        if not place_id:
            continue
        catalog[place_id] = PlaceInsight(
            place_id=place_id,
            place_name=entry.get("placeName", ""),
            scene_hint=entry.get("sceneHint", ""),
            lighting_hint=entry.get("lightingHint", ""),
            mood_tags=tuple(entry.get("moodTags", [])),
            notable_features=tuple(entry.get("notableFeatures", [])),
        )
    return catalog


def get_place_insight(place_id: str) -> PlaceInsight | None:
    return load_place_insights().get(place_id)
