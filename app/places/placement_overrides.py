"""사진 단위 배치 보정 로더.

`assets/places/placement_overrides.json`은 사람이 합성 결과를 보고 직접 쓰는 보정이다.
VLM 분석(`place_insights.json`)이 한 사진에서 서로 충돌하는 배치 값을 내거나, 장소 공통
지침(`pose_guides.json`)이 그 사진에 없는 요소를 지목할 때 그 사진 하나만 바로잡는다.
분석 스크립트가 덮어쓰지 않도록 별도 파일로 둔다.

파일이 없거나 매칭되는 사진이 없으면 아무것도 바꾸지 않는다.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, replace
from functools import lru_cache
from typing import TYPE_CHECKING

from app.core.config import get_settings

if TYPE_CHECKING:
    from app.places.backgrounds import PlaceContext

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PlacementOverride:
    standable_surface: str | None = None
    subject_zone: str | None = None
    # None이면 분석값 유지, 빈 튜플이면 "가림 요소 없음"으로 덮어쓴다.
    occluding_elements: tuple[str, ...] | None = None
    # 있으면 장소 공통 포즈 지침을 대체한다 (그 사진에 맞지 않는 지침이 섞이지 않게).
    pose_direction: str | None = None
    pose_negative: str | None = None

    def apply(self, context: PlaceContext) -> PlaceContext:
        changes: dict[str, str] = {}
        if self.standable_surface:
            changes["ground_plane"] = self.standable_surface
        if self.subject_zone:
            changes["subject_zone"] = self.subject_zone
        if self.occluding_elements is not None:
            changes["occluding_elements"] = ", ".join(self.occluding_elements)
        if self.pose_direction:
            changes["pose_direction"] = self.pose_direction
            changes["pose_negative"] = self.pose_negative or ""
        return replace(context, **changes)


@lru_cache
def load_placement_overrides() -> dict[str, PlacementOverride]:
    path = get_settings().places_dir / "placement_overrides.json"
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("placement_overrides.json을 읽지 못해 보정 없이 진행합니다.", exc_info=True)
        return {}

    overrides: dict[str, PlacementOverride] = {}
    for url, item in (raw.get("images") or {}).items():
        occluding = item.get("occludingElements")
        overrides[url] = PlacementOverride(
            standable_surface=item.get("standableSurface") or None,
            subject_zone=item.get("suggestedSubjectZone") or None,
            occluding_elements=tuple(occluding) if isinstance(occluding, list) else None,
            pose_direction=item.get("poseDirection") or None,
            pose_negative=item.get("poseNegative") or None,
        )
    return overrides


def get_placement_override(image_url: str | None) -> PlacementOverride | None:
    if not image_url:
        return None
    return load_placement_overrides().get(image_url)
