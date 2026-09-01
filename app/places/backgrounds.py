"""배경 이미지 카탈로그 — 로컬 개발·수동 테스트 전용.

**중요**: 이 카탈로그의 `id` 값(예: `anmok-beach`)은 백엔드의 실제 `Place.id`와
아무 관계가 없다. 백엔드 `07_DATA_MODEL.md`에 따르면 `CompositionJob.onePickPlaceId`는
`Place` 테이블의 UUID 기본키를 가리키는 FK다. 즉 운영 환경에서 이 서비스가 실제로
받는 `onePickPlaceId`는 UUID이고, 이 카탈로그로는 절대 매칭되지 않는다.

백엔드는 관광지 이미지를 파일로 갖고 있지 않다. `Place.thumbnailUrl` /
`PlaceImage.imageUrl`은 한국관광공사가 직접 호스팅하는 원격 URL 문자열이다
(`PlaceService.upsert()` 참고). 따라서 **실제 배경 이미지는 백엔드가
`POST /v1/generations`의 `background` 파일 필드로 보내야 한다** — 백엔드가
Tour API 이미지 URL에서 바이트를 가져와 전달하는 구조다. 상세:
`docs/AI_API_CONTRACT.md`.

이 카탈로그는 그 경로가 아직 없을 때(`AI_PROVIDER=mock` 개발, curl로 수동 테스트)
합성 파이프라인을 끝까지 돌려보기 위한 것일 뿐이다. 모든 항목은 저작권 확인 전이라
`usable=false`로 고정돼 있다 (요구사항 C3).
"""

from __future__ import annotations

import io
import json
import logging
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path

from PIL import Image

from app.core.config import get_settings
from app.places.insights import ImageInsight, get_image_insight
from app.places.outfit_guides import (
    get_composition_rules,
    get_outfit_common,
    get_outfit_scene_type,
)
from app.places.pose_guides import get_pose_guide, get_scene_type_guides
from app.providers.base import BackgroundAnalysis

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DevBackgroundPlace:
    id: str
    name: str
    region: str
    file: str
    scene_hint: str
    lighting_hint: str
    usable: bool


@dataclass(frozen=True)
class PlaceContext:
    """프롬프트에 주입할 장소·장면 설명. 합성 배경 바이트와는 별개다.

    `light_direction` 이하 필드는 `place_insights.json`의 이미지별 VLM 분석이
    매칭됐을 때 그 값으로 채워진다 — 선택된 배경 사진 고유의 카메라/인물 배치
    정보라 다른 우선순위 경로(개발 카탈로그, 실시간 분석, 백엔드 텍스트 필드,
    범용 문구)에서는 알 수 없다. 기본값은 매칭이 없을 때도 프롬프트 문장이
    깨지지 않도록 넣어둔 일반적인 문구다 — 실제 서비스 플로우에서는 사용자가
    사전 분석된 사진 중에서만 고르므로 이 기본값은 사실상 안전망이다.
    """

    name: str
    scene_hint: str
    lighting_hint: str
    time_of_day: str = "as shown in the background photo"
    light_direction: str = "as shown in the background photo"
    light_angle: str = "as shown in the background photo"
    color_temperature: str = "as shown in the background photo"
    shadow_hardness: str = "as shown in the background photo"
    camera_perspective: str = "as shown in the background photo"
    horizon_position: str = "as shown in the background photo"
    suggested_framing: str = "full-body"
    ground_plane: str = "the visible ground/surface in the background photo"
    subject_zone: str = "a natural standing position within the frame"
    occluding_elements: str = ""
    mood_tags: str = "a natural travel-photo mood"
    color_palette: str = "the background photo's natural colors"
    season: str = ""
    # 팀이 조사한 장소별 포즈 지침 (assets/places/pose_guides.json). 조사 문서에
    # 없는 장소는 빈 문자열이고, 프롬프트는 일반적인 포즈 지시만 쓴다.
    pose_direction: str = ""
    # 팀이 조사한 의상 지침 (assets/places/outfit_guides.json). 비어 있으면
    # 프롬프트가 "원본 옷을 유지하라"는 기본 문구만 쓴다.
    outfit_direction: str = ""
    outfit_negative: str = ""
    pose_negative: str = ""


@lru_cache
def load_dev_catalog() -> dict[str, DevBackgroundPlace]:
    path = get_settings().backgrounds_dir / "backgrounds.json"
    if not path.is_file():
        return {}

    raw = json.loads(path.read_text(encoding="utf-8"))
    catalog: dict[str, DevBackgroundPlace] = {}
    for entry in raw.get("places", []):
        place = DevBackgroundPlace(
            id=entry["id"],
            name=entry.get("name", entry["id"]),
            region=entry.get("region", ""),
            file=entry.get("file", ""),
            scene_hint=entry.get("sceneHint", ""),
            lighting_hint=entry.get("lightingHint", ""),
            usable=bool(entry.get("usable", False)),
        )
        catalog[place.id] = place
    return catalog


def get_dev_place(one_pick_place_id: str) -> DevBackgroundPlace | None:
    return load_dev_catalog().get(one_pick_place_id)


def load_dev_background_image(one_pick_place_id: str) -> tuple[bytes, str] | None:
    """개발용 카탈로그에서 실제 사용 가능한(`usable=true`) 배경 파일을 찾는다.

    운영에서 이 함수가 값을 돌려주는 일은 없어야 한다 — `onePickPlaceId`가
    카탈로그 키와 매칭되지 않거나(UUID vs 슬러그), 매칭되더라도 저작권 미확인으로
    `usable=false`이기 때문이다. 매칭되는 실제 파일이 없으면 `None`을 돌려주고,
    호출자가 `background` 업로드를 요구하거나(운영) 플레이스홀더를 쓰거나(mock
    개발) 결정한다.
    """
    place = get_dev_place(one_pick_place_id)
    if place is None or not place.usable or not place.file:
        return None

    path: Path = get_settings().backgrounds_dir / place.file
    if not path.is_file():
        return None

    mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    return path.read_bytes(), mime


def placeholder_background(width: int = 1024, height: int = 1280) -> bytes:
    """하늘색에서 모래색으로 흐르는 세로 그라디언트. `AI_PROVIDER=mock` 전용 폴백."""
    image = Image.new("RGB", (width, height))
    top = (126, 178, 214)
    bottom = (232, 214, 184)
    pixels = image.load()
    for y in range(height):
        t = y / max(1, height - 1)
        row = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
        for x in range(width):
            pixels[x, y] = row

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def has_precomputed_place_context(
    one_pick_place_id: str, background_image_url: str | None = None
) -> bool:
    """1·2순위(개발용 카탈로그, 오프라인 VLM 캐시)가 이미 매칭되는지만 가볍게 확인한다.

    `app/jobs/runner.py`가 이 함수로 캐시 히트 여부를 먼저 확인해, 미스일 때만
    (대부분의 실제 요청 — award-photos/tourism-photos에서 고른 배경은
    `onePickPlaceId`가 `Place` UUID가 아니라 캐시에 애초에 매칭되지 않는다)
    `provider.analyze_background()`를 호출해 비용을 아낀다.
    """
    dev_place = get_dev_place(one_pick_place_id)
    if dev_place is not None and dev_place.usable:
        return True
    return get_image_insight(one_pick_place_id, background_image_url) is not None


def resolve_place_context(
    one_pick_place_id: str,
    *,
    place_name: str | None,
    place_region: str | None,
    place_description: str | None,
    background_analysis: BackgroundAnalysis | None = None,
    background_image_url: str | None = None,
) -> PlaceContext:
    """프롬프트에 넣을 장소명·장면·조명·카메라·인물 배치 정보를 결정한다.

    우선순위:
    1. 개발용 카탈로그가 `usable=true`로 매칭되면 그 장면/조명 힌트를 쓴다
       (로컬 개발·데모 전용, 운영에서는 사실상 발생하지 않는다).
    2. `place_insights.json`에 실제 `Place.id`로 매칭되는 VLM 사전 분석 리포트가
       있으면 그 장면/조명/분위기를 쓴다 — Type1(변경 허용) 라이선스 이미지가 많은
       상위 N개 장소만 대상이라 모든 요청에 매칭되지는 않는다 (`docs/adr/
       0003-place-image-vlm-analysis.md`). `background_image_url`(사용자가 프론트
       에서 고른 사진의 원본 URL)이 함께 오면 그 사진 정확히 하나의 분석을 쓰고,
       없거나 매칭되는 사진이 없으면 그 장소의 대표(첫 번째) 이미지로 폴백한다.
    3. 1·2가 모두 미스면, 호출자가 이번 요청의 실제 배경 이미지를 실시간 분석해
       넘긴 `background_analysis`를 쓴다 — 백엔드의 award-photos/tourism-photos
       탭에서 고른 배경은 `Place` UUID가 아닌 ID를 가져 1·2에 매칭될 수 없으므로,
       ID가 아니라 이번 요청의 이미지 바이트 자체를 근거로 삼는다 (`docs/adr/
       0004-realtime-background-analysis.md`).
    4. 백엔드가 `placeName`/`placeRegion`/`placeDescription`을 보냈으면 그 값을
       쓴다 — 백엔드 `Place` 테이블에 이미 있는 정보이므로 별도 조회 없이 활용한다.
       (3이 시도됐지만 실패해 빈 분석만 돌아온 경우의 폴백이기도 하다.)
    5. 넷 다 없으면 범용 문구로 채운다.

    어느 경로로 결정됐든, 마지막에 장소별 포즈 지침(`pose_guides.json`)과 의상
    지침(`outfit_guides.json`)을 붙인다 — 둘 다 사진이 아니라 장소·장면 유형에
    딸린 정보라 위 우선순위와 무관하다.
    """
    insight = get_image_insight(one_pick_place_id, background_image_url)
    context = _resolve_place_context(
        one_pick_place_id,
        place_name=place_name,
        place_region=place_region,
        place_description=place_description,
        background_analysis=background_analysis,
        background_image_url=background_image_url,
    )
    return _with_outfit_guide(_with_pose_guide(context, insight), insight)


def _with_outfit_guide(context: PlaceContext, insight: ImageInsight | None) -> PlaceContext:
    """장면 유형 의상 규칙 + 구도 배치 규칙을 붙인다.

    공통 규칙(원본 옷 유지, 옷의 물리, 장면 광 반영)은 매칭 여부와 무관하게 항상
    넣는다 — 의상이 통째로 바뀌는 사고는 매칭되지 않은 장소에서도 똑같이 난다.
    """
    common = get_outfit_common()
    text = ""
    if insight is not None:
        text = " ".join(
            [
                insight.scene_hint,
                context.ground_plane,
                context.subject_zone,
                *insight.notable_features,
            ]
        )

    lines = [common.garment_reference]
    scene = get_outfit_scene_type(context.name, text)
    if scene is not None:
        lines.append(f"[{scene.label}] {scene.prompt}")
    lines.extend(rule.prompt for rule in get_composition_rules(text))
    lines.extend([common.garment_physics, common.scene_fit])

    negatives = [common.negative]
    if scene is not None and scene.negative:
        negatives.append(scene.negative)

    return replace(
        context,
        outfit_direction="\n".join(f"- {line}" for line in lines if line),
        outfit_negative=", ".join(n for n in negatives if n),
    )


def _with_pose_guide(context: PlaceContext, insight: ImageInsight | None) -> PlaceContext:
    """장소 지침 + 이 사진의 성격에 맞는 장면 유형 지침을 붙인다.

    장면 유형 지침을 뒤에 두는 것은 의도적이다 — 장소 지침이 그 장소의 '대표
    구도'를 전제해 이 사진에는 없는 요소(데크, 산책로)를 지목할 때가 있는데,
    사진 자체에서 유도한 지침이 뒤에 와야 그쪽을 따르게 된다.
    """
    directions, negatives = [], []
    guide = get_pose_guide(context.name)
    if guide is not None:
        directions.append(guide.prompt)
        negatives.append(guide.negative)

    if insight is not None:
        text = " ".join([insight.scene_hint, *insight.notable_features])
        for scene in get_scene_type_guides(insight.season, text):
            directions.append(f"[{scene.label}] {scene.prompt}")
            negatives.append(scene.negative)

    if not directions:
        return context
    return replace(
        context,
        pose_direction="\n\n".join(directions),
        pose_negative=", ".join(n for n in negatives if n),
    )


def _resolve_place_context(
    one_pick_place_id: str,
    *,
    place_name: str | None,
    place_region: str | None,
    place_description: str | None,
    background_analysis: BackgroundAnalysis | None = None,
    background_image_url: str | None = None,
) -> PlaceContext:
    dev_place = get_dev_place(one_pick_place_id)
    if dev_place is not None and dev_place.usable:
        return PlaceContext(dev_place.name, dev_place.scene_hint, dev_place.lighting_hint)

    insight = get_image_insight(one_pick_place_id, background_image_url)
    if insight is not None:
        name = place_name or insight.place_name
        return PlaceContext(
            name=name,
            scene_hint=insight.as_scene_hint(),
            lighting_hint=insight.as_lighting_hint(),
            time_of_day=insight.lighting.get("timeOfDay") or PlaceContext.time_of_day,
            light_direction=insight.lighting.get("direction") or PlaceContext.light_direction,
            light_angle=insight.lighting.get("angle") or PlaceContext.light_angle,
            color_temperature=insight.lighting.get("colorTemperature")
            or PlaceContext.color_temperature,
            shadow_hardness=insight.lighting.get("shadowHardness") or PlaceContext.shadow_hardness,
            camera_perspective=insight.camera.get("perspective") or PlaceContext.camera_perspective,
            horizon_position=insight.camera.get("horizonPosition") or PlaceContext.horizon_position,
            suggested_framing=insight.camera.get("suggestedFraming")
            or PlaceContext.suggested_framing,
            # 인물을 세울 곳은 "프레임 하단에 보이는 지면"(groundPlane)이 아니라
            # "실제로 두 발로 설 수 있는 표면"(standableSurface)이다. 바위 해안·
            # 수면·차도가 groundPlane으로 잡히는 사진이 많아, 이걸 그대로 쓰면
            # 사람이 설 수 없는 곳에 세우게 된다.
            #
            # standableSurface가 비어 있으면 groundPlane으로 폴백하지 않는다 —
            # 그 값이야말로 방금 "설 수 없다"고 판정해 비운 바로 그 지면이라,
            # 되돌리면 항공샷에 "rocky shore에 세우라"고 지시하게 된다. 대신
            # 일반 문구를 써서 합성 모델이 알아서 설 만한 곳을 찾게 둔다.
            ground_plane=insight.placement.get("standableSurface") or PlaceContext.ground_plane,
            subject_zone=insight.placement.get("suggestedSubjectZone") or PlaceContext.subject_zone,
            occluding_elements=", ".join(insight.placement.get("occludingElements", [])),
            mood_tags=", ".join(insight.mood_tags) or PlaceContext.mood_tags,
            color_palette=", ".join(insight.color_palette) or PlaceContext.color_palette,
            season=insight.season,
        )

    if background_analysis is not None and (
        background_analysis.scene_description or background_analysis.lighting
    ):
        name = place_name or "강릉의 관광지"
        parts = (
            [background_analysis.scene_description] if background_analysis.scene_description else []
        )
        if background_analysis.notable_features:
            parts.append("눈에 띄는 요소: " + ", ".join(background_analysis.notable_features))
        if background_analysis.mood_tags:
            parts.append("분위기: " + ", ".join(background_analysis.mood_tags))
        scene = " ".join(parts) or (place_description or "강릉의 대표적인 관광 명소")
        lighting = background_analysis.lighting or "배경 사진에 보이는 조명 조건을 그대로 따를 것"
        return PlaceContext(name, scene, lighting)

    name = place_name or "강릉의 관광지"
    if place_description:
        scene = place_description
    elif place_region:
        scene = f"{place_region}에 위치한 관광지"
    else:
        scene = "강릉의 대표적인 관광 명소"
    lighting = "배경 사진에 보이는 조명 조건을 그대로 따를 것"
    return PlaceContext(name, scene, lighting)
