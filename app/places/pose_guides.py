"""장소별 포즈·배치 가이드 로더.

`assets/places/pose_guides.json`은 팀이 직접 조사해 작성한 자산이다 —
`place_insights.json`(VLM이 생성)과 달리 사람이 쓴 지침이라, 배치 스크립트가
덮어쓰지 않는다.

합성 프롬프트는 두 출처를 함께 쓴다:
    - place_insights.json : 이 **사진**의 조명·카메라·설 자리 (기계 분석)
    - pose_guides.json    : 이 **장소**에서 인물을 어떻게 세울지 (사람 조사)

파일이 없거나 매칭되는 장소가 없어도 서비스는 정상 동작해야 한다 — 그 경우
프롬프트는 기존의 일반적인 포즈 지시만 쓴다.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from functools import lru_cache

from app.core.config import get_settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PoseGuide:
    """한 장소의 포즈 지침."""

    name: str
    photo_type: str
    prompt: str
    negative: str


@dataclass(frozen=True)
class SceneTypeGuide:
    """사진의 성격으로 매칭되는 지침 (장소가 아니라).

    같은 장소에도 성격이 아주 다른 사진이 섞여 있다 — 국립대관령치유의숲에는
    숲길 사진과 단풍 접사가 함께 있는데, 후자에 "데크 난간 안쪽에 세우라"는 장소
    지침을 적용하면 모델이 없는 지면을 지어낸다.
    """

    id: str
    label: str
    seasons: tuple[str, ...]
    keywords: tuple[str, ...]
    prompt: str
    negative: str

    def matches(self, season: str, text: str) -> bool:
        """계절과 장면 설명이 모두 맞아야 적용한다.

        계절만 보면 '가을에 찍힌 성당·바다' 사진까지 걸린다 — 그런 사진은 단풍이
        주피사체가 아니라서 이 지침이 오히려 방해가 된다.
        """
        if self.seasons and season not in self.seasons:
            return False
        return any(k in text for k in self.keywords)


@dataclass(frozen=True)
class CommonGuide:
    """모든 장소에 공통으로 적용되는 지침."""

    background_preservation: str = ""
    framing_by_composition: str = ""
    negative: str = ""


@lru_cache
def load_pose_guides() -> tuple[CommonGuide, dict[str, PoseGuide], tuple[SceneTypeGuide, ...]]:
    """(공통 지침, 장소명 -> 포즈 지침, 장면 유형 지침들). 별칭도 같은 지침으로 색인한다."""
    path = get_settings().places_dir / "pose_guides.json"
    if not path.is_file():
        return CommonGuide(), {}, ()

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("pose_guides.json을 읽지 못했습니다.")
        return CommonGuide(), {}, ()

    common_raw = raw.get("common", {})
    common = CommonGuide(
        background_preservation=common_raw.get("backgroundPreservation", ""),
        framing_by_composition=common_raw.get("framingByComposition", ""),
        negative=common_raw.get("negative", ""),
    )

    by_name: dict[str, PoseGuide] = {}
    for entry in raw.get("places", []):
        name = entry.get("name")
        if not name:
            continue
        guide = PoseGuide(
            name=name,
            photo_type=entry.get("photoType", ""),
            prompt=entry.get("prompt", ""),
            negative=entry.get("negative", ""),
        )
        # 조사 문서의 장소명과 백엔드 Place.name이 다른 경우가 있어 별칭도 받는다.
        for key in [name, *entry.get("aliases", [])]:
            by_name[key] = guide

    scene_types = tuple(
        SceneTypeGuide(
            id=entry.get("id", ""),
            label=entry.get("label", ""),
            seasons=tuple(entry.get("match", {}).get("season", [])),
            keywords=tuple(entry.get("match", {}).get("anyKeyword", [])),
            prompt=entry.get("prompt", ""),
            negative=entry.get("negative", ""),
        )
        for entry in raw.get("sceneTypes", [])
    )
    return common, by_name, scene_types


def get_pose_guide(place_name: str | None) -> PoseGuide | None:
    """장소명으로 포즈 지침을 찾는다. 이름이 정확히 맞아야 한다.

    부분 일치는 하지 않는다 — '강문해변'에 '강문솟대다리'의 "다리 중앙을 막지
    말라"는 지침이 붙는 식의 오적용이 실제로 위험하다. 새 장소는 조사 문서에
    항목을 추가하거나 `aliases`로 연결한다.
    """
    if not place_name:
        return None
    return load_pose_guides()[1].get(place_name.strip())


def get_common_guide() -> CommonGuide:
    return load_pose_guides()[0]


def get_scene_type_guides(season: str, text: str) -> list[SceneTypeGuide]:
    """이 사진의 성격에 맞는 장면 유형 지침. 없으면 빈 리스트."""
    return [g for g in load_pose_guides()[2] if g.matches(season or "", text or "")]


__all__ = [
    "PoseGuide",
    "CommonGuide",
    "SceneTypeGuide",
    "load_pose_guides",
    "get_pose_guide",
    "get_common_guide",
    "get_scene_type_guides",
]
