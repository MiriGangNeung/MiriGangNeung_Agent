"""장소별 의상 지침 로더.

`assets/places/outfit_guides.json`은 팀이 Notion에 작성한 '미리강릉 포즈 조사3
(사람들 옷)' 문서를 재구성한 자산이다 — `pose_guides.json`과 마찬가지로 사람이
쓴 지침이라 배치 스크립트가 덮어쓰지 않는다.

합성 프롬프트가 쓰는 세 출처:
    - place_insights.json : 이 **사진**의 조명·카메라·설 자리 (기계 분석)
    - pose_guides.json    : 이 **장소**에서 인물을 어떻게 세울지 (사람 조사)
    - outfit_guides.json  : 이 **장면 유형**에서 옷을 어떻게 다룰지 (사람 조사)

매칭은 두 단계다. 장소명이 문서에 있으면 그 유형을 쓰고, 없으면 장면 설명
키워드로 유형을 찾는다 — 원문의 43개 장소는 표본이라 실제 서비스가 받는 장소를
다 덮지 못하는데, 규칙 자체는 장소가 아니라 장면 유형에 붙어 있어서 키워드로도
정확히 고를 수 있다.

파일이 없거나 매칭이 없어도 서비스는 정상 동작해야 한다 — 그 경우 프롬프트는
공통 의상 규칙만 쓴다.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from functools import lru_cache

from app.core.config import get_settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OutfitCommon:
    """장면 유형과 무관하게 항상 적용되는 의상 규칙."""

    garment_reference: str = ""
    garment_physics: str = ""
    scene_fit: str = ""
    negative: str = ""


@dataclass(frozen=True)
class OutfitSceneType:
    """장면 유형 하나의 의상 규칙."""

    id: str
    label: str
    places: tuple[str, ...]
    keywords: tuple[str, ...]
    prompt: str
    negative: str

    def matches_place(self, place_name: str) -> bool:
        return place_name in self.places

    def matches_text(self, text: str) -> bool:
        return any(k in text for k in self.keywords)


@dataclass(frozen=True)
class CompositionRule:
    """사진의 구도 성격에 붙는 배치 규칙 (인물 크기 상한·접지·가림 금지)."""

    id: str
    label: str
    keywords: tuple[str, ...]
    prompt: str

    def matches_text(self, text: str) -> bool:
        return any(k in text for k in self.keywords)


_LoadedGuides = tuple[OutfitCommon, tuple[OutfitSceneType, ...], tuple[CompositionRule, ...]]


@lru_cache
def load_outfit_guides() -> _LoadedGuides:
    path = get_settings().places_dir / "outfit_guides.json"
    if not path.is_file():
        return OutfitCommon(), (), ()

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("outfit_guides.json을 읽지 못했습니다.")
        return OutfitCommon(), (), ()

    common_raw = raw.get("common", {})
    common = OutfitCommon(
        garment_reference=common_raw.get("garmentReference", ""),
        garment_physics=common_raw.get("garmentPhysics", ""),
        scene_fit=common_raw.get("sceneFit", ""),
        negative=common_raw.get("negative", ""),
    )

    scene_types = tuple(
        OutfitSceneType(
            id=entry.get("id", ""),
            label=entry.get("label", ""),
            places=tuple(entry.get("places", [])),
            keywords=tuple(entry.get("anyKeyword", [])),
            prompt=entry.get("prompt", ""),
            negative=entry.get("negative", ""),
        )
        for entry in raw.get("sceneTypes", [])
    )

    composition_rules = tuple(
        CompositionRule(
            id=entry.get("id", ""),
            label=entry.get("label", ""),
            keywords=tuple(entry.get("anyKeyword", [])),
            prompt=entry.get("prompt", ""),
        )
        for entry in raw.get("compositionRules", [])
    )
    return common, scene_types, composition_rules


def get_outfit_common() -> OutfitCommon:
    return load_outfit_guides()[0]


def get_outfit_scene_type(place_name: str | None, text: str | None) -> OutfitSceneType | None:
    """이 장소/사진에 맞는 의상 유형 하나. 장소명 일치가 키워드 매칭보다 우선한다.

    키워드 매칭은 첫 번째로 걸린 유형만 쓴다. 여러 유형을 겹쳐 붙이면 "젖은 옷
    금지"와 "물놀이면 래시가드 허용"처럼 서로 반대되는 지시가 한 프롬프트에
    같이 들어간다.
    """
    _, scene_types, _ = load_outfit_guides()
    name = (place_name or "").strip()
    if name:
        for scene in scene_types:
            if scene.matches_place(name):
                return scene
    body = text or ""
    if body:
        for scene in scene_types:
            if scene.matches_text(body):
                return scene
    return None


def get_composition_rules(text: str | None) -> list[CompositionRule]:
    """이 사진의 구도 성격에 맞는 배치 규칙들. 없으면 빈 리스트."""
    if not text:
        return []
    return [rule for rule in load_outfit_guides()[2] if rule.matches_text(text)]


__all__ = [
    "OutfitCommon",
    "OutfitSceneType",
    "CompositionRule",
    "load_outfit_guides",
    "get_outfit_common",
    "get_outfit_scene_type",
    "get_composition_rules",
]
