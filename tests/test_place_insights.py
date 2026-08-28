"""장소 특징 VLM 사전 분석 — 런타임 로더 + 배치 스크립트 순수 로직 단위 테스트.

배치 스크립트(`scripts/analyze_top_places.py`)의 네트워크 호출(백엔드 API, 이미지
다운로드, HF 추론)은 여기서 검증하지 않는다 — 순수 함수(선정·필터·병합·파싱)만
테스트해서 실제 HF_TOKEN이나 네트워크 없이 CI가 통과하도록 한다.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.places.backgrounds import (  # noqa: E402
    has_precomputed_place_context,
    resolve_place_context,
)
from app.places.insights import (  # noqa: E402
    get_image_insight,
    get_place_insight,
    load_place_insights,
    viable_images,
)
from app.providers.base import BackgroundAnalysis  # noqa: E402
from scripts.analyze_top_places import (  # noqa: E402
    PlaceCandidate,
    PlaceImageRef,
    analysis_from_payload,
    build_report,
    cap_images,
    filter_type1_images,
    merge_place_insight,
    parse_vlm_json,
    select_top_places,
)

# ── filter_type1_images / select_top_places / cap_images ────────────


def test_filter_type1_images_drops_type3_and_blank_urls():
    images = [
        {"imageUrl": "https://x/1.jpg", "copyrightCode": "Type1", "sortOrder": 1},
        {"imageUrl": "https://x/2.jpg", "copyrightCode": "Type3", "sortOrder": 0},
        {"imageUrl": "", "copyrightCode": "Type1", "sortOrder": 2},
        {"imageUrl": "https://x/3.jpg", "copyrightCode": "Type1", "sortOrder": 0},
    ]

    result = filter_type1_images(images)

    assert [i.url for i in result] == ["https://x/1.jpg", "https://x/3.jpg"]


def test_select_top_places_ranks_by_type1_image_count_and_excludes_empty():
    def candidate(place_id: str, count: int) -> PlaceCandidate:
        images = [
            PlaceImageRef(url=f"{place_id}-{i}", title=None, sort_order=i) for i in range(count)
        ]
        return PlaceCandidate(place_id=place_id, place_name=place_id, type1_images=images)

    candidates = [candidate("a", 2), candidate("b", 5), candidate("c", 0), candidate("d", 3)]

    top = select_top_places(candidates, top_n=2)

    assert [c.place_id for c in top] == ["b", "d"]


def test_select_top_places_excludes_places_below_min_images():
    def candidate(place_id: str, count: int) -> PlaceCandidate:
        images = [
            PlaceImageRef(url=f"{place_id}-{i}", title=None, sort_order=i) for i in range(count)
        ]
        return PlaceCandidate(place_id=place_id, place_name=place_id, type1_images=images)

    candidates = [candidate("a", 5), candidate("b", 3), candidate("c", 5), candidate("d", 1)]

    top = select_top_places(candidates, top_n=10, min_images=5)

    assert [c.place_id for c in top] == ["a", "c"]


def test_cap_images_sorts_by_sort_order_then_limits():
    images = [
        PlaceImageRef(url="third", title=None, sort_order=2),
        PlaceImageRef(url="first", title=None, sort_order=0),
        PlaceImageRef(url="second", title=None, sort_order=1),
    ]

    capped = cap_images(images, limit=2)

    assert [i.url for i in capped] == ["first", "second"]


# ── parse_vlm_json ────────────────────────────────────────────────


def test_parse_vlm_json_strips_markdown_fence():
    text = '```json\n{"sceneHint": "해변"}\n```'

    assert parse_vlm_json(text) == {"sceneHint": "해변"}


def test_parse_vlm_json_returns_empty_dict_on_malformed_input():
    assert parse_vlm_json("이건 JSON이 아님") == {}
    assert parse_vlm_json("") == {}


# ── analysis_from_payload ────────────────────────────────────────


def test_analysis_from_payload_fills_schema_defaults_for_missing_fields():
    analysis = analysis_from_payload({"sceneHint": "해변 풍경"})

    assert analysis["sceneHint"] == "해변 풍경"
    assert analysis["moodTags"] == []
    assert analysis["lighting"] == {
        "timeOfDay": "",
        "direction": "",
        "angle": "",
        "colorTemperature": "",
        "shadowHardness": "",
    }
    assert analysis["camera"] == {"perspective": "", "horizonPosition": "", "suggestedFraming": ""}
    assert analysis["placement"] == {
        "groundPlane": "",
        "standableSurface": "",
        "suggestedSubjectZone": "",
        "occludingElements": [],
    }
    assert analysis["season"] == "unknown"
    # 설 자리 정보가 없으면 배경으로 쓸 수 없다고 보수적으로 판정한다.
    assert analysis["portraitViability"] == "low"


def test_analysis_from_payload_passes_through_nested_fields():
    payload = {
        "sceneHint": "해변 풍경",
        "moodTags": ["평화로운"],
        "notableFeatures": ["백사장"],
        "lighting": {"timeOfDay": "goldenHour", "direction": "back-left"},
        "camera": {"perspective": "eye-level"},
        "placement": {
            "groundPlane": "sand beach, lower-center",
            "standableSurface": "dry sand, lower-left",
            "suggestedSubjectZone": "center-left",
            "occludingElements": ["울타리"],
        },
        "distractions": [],
        "sceneAppeal": "high",
        "viabilityReason": "넓은 백사장이 있어 서기 좋다",
        "colorPalette": ["#4a6b3a"],
        "season": "summer",
    }

    analysis = analysis_from_payload(payload)

    assert analysis["lighting"]["timeOfDay"] == "goldenHour"
    assert analysis["lighting"]["direction"] == "back-left"
    assert analysis["camera"]["perspective"] == "eye-level"
    assert analysis["placement"]["standableSurface"] == "dry sand, lower-left"
    assert analysis["placement"]["suggestedSubjectZone"] == "center-left"
    assert analysis["placement"]["occludingElements"] == ["울타리"]
    assert analysis["portraitViability"] == "high"
    assert analysis["colorPalette"] == ["#4a6b3a"]
    assert analysis["season"] == "summer"


# ── 설 자리 판정 (2차 배치에서 추가) ──────────────────────────────


@pytest.mark.parametrize("none_value", ["none", "None", "N/A", "없음", "", "  "])
def test_analysis_from_payload_treats_none_like_values_as_no_surface(none_value):
    """모델이 '설 자리 없음'을 여러 표기로 답해도 전부 빈 값으로 통일한다."""
    analysis = analysis_from_payload(
        {"placement": {"standableSurface": none_value, "suggestedSubjectZone": "center"}}
    )

    assert analysis["placement"]["standableSurface"] == ""
    # 설 자리가 없으면 인물 위치도 성립하지 않는다.
    assert analysis["placement"]["suggestedSubjectZone"] == ""
    assert analysis["portraitViability"] == "low"


def test_analysis_from_payload_downgrades_viability_when_nowhere_to_stand():
    """설 자리가 없는데 high라고 답하면 그 판정을 믿지 않는다."""
    analysis = analysis_from_payload(
        {
            "placement": {"groundPlane": "rocky shore", "standableSurface": "none"},
            "sceneAppeal": "high",
        }
    )

    assert analysis["portraitViability"] == "low"


@pytest.mark.parametrize(
    "surface",
    ["wet rocks", "wet rocks, lower-left", "rocky shore", "water surface", "wooden table"],
)
def test_analysis_from_payload_rejects_surfaces_nobody_can_stand_on(surface):
    """모델이 바위·수면·테이블을 설 자리로 답해도 코드가 막는다."""
    analysis = analysis_from_payload(
        {
            "placement": {"standableSurface": surface, "suggestedSubjectZone": "lower-left"},
            "sceneAppeal": "high",
        }
    )

    assert analysis["placement"]["standableSurface"] == ""
    assert analysis["placement"]["suggestedSubjectZone"] == ""
    assert analysis["portraitViability"] == "low"


@pytest.mark.parametrize(
    "surface",
    [
        "dry sand, lower-left",
        "paved path, center",
        "pavement clear of traffic",  # "traffic"이 들어가도 정상 답변이다
        "wooden deck",
        "grass",
    ],
)
def test_analysis_from_payload_keeps_genuinely_standable_surfaces(surface):
    analysis = analysis_from_payload(
        {
            "placement": {"standableSurface": surface, "suggestedSubjectZone": "center"},
            "sceneAppeal": "high",
        }
    )

    assert analysis["placement"]["standableSurface"] == surface
    assert analysis["portraitViability"] == "high"


def test_analysis_from_payload_rejects_unknown_viability_value():
    analysis = analysis_from_payload(
        {"placement": {"standableSurface": "dry sand"}, "sceneAppeal": "excellent"}
    )

    assert analysis["portraitViability"] == "low"


# ── merge_place_insight ──────────────────────────────────────────


def test_merge_place_insight_keeps_each_image_analysis_separate():
    primary_ref = PlaceImageRef(url="primary", title=None, sort_order=1)
    other_ref = PlaceImageRef(url="other", title=None, sort_order=0)
    primary = analysis_from_payload({"sceneHint": "해변 풍경", "moodTags": ["평화로운"]})
    other = analysis_from_payload({"sceneHint": "소나무 숲", "moodTags": ["여름"]})

    insight = merge_place_insight(
        "place-1",
        "안목해변",
        type1_image_count=8,
        analyzed=[(primary_ref, primary), (other_ref, other)],
    )

    assert insight is not None
    assert insight.type1_image_count == 8
    assert insight.analyzed_image_count == 2
    # sort_order 오름차순 — other(0)가 primary(1)보다 앞선다.
    assert [img["sourceUrl"] for img in insight.images] == ["other", "primary"]
    assert insight.images[0]["sceneHint"] == "소나무 숲"
    assert insight.images[1]["sceneHint"] == "해변 풍경"


def test_merge_place_insight_returns_none_when_nothing_analyzed():
    assert merge_place_insight("place-1", "안목해변", type1_image_count=3, analyzed=[]) is None


def test_build_report_shape():
    ref = PlaceImageRef(url="primary", title=None, sort_order=0)
    analysis = analysis_from_payload({"sceneHint": "해변"})
    insight = merge_place_insight("place-1", "안목해변", 1, [(ref, analysis)])

    report = build_report("some/model", "hf-inference-api", top_n=10, insights=[insight])

    assert report["topN"] == 10
    assert report["model"] == "some/model"
    assert report["source"] == "hf-inference-api"
    assert report["places"][0]["placeId"] == "place-1"
    assert report["places"][0]["images"][0]["sceneHint"] == "해변"
    assert report["places"][0]["images"][0]["sourceUrl"] == "primary"


# ── 런타임 로더 (app/places/insights.py) ─────────────────────────


@pytest.fixture
def insights_file(tmp_path, monkeypatch):
    def _write(payload: dict) -> Path:
        path = tmp_path / "place_insights.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        fake_settings = types.SimpleNamespace(places_dir=tmp_path)
        monkeypatch.setattr("app.places.insights.get_settings", lambda: fake_settings)
        load_place_insights.cache_clear()
        return path

    yield _write
    load_place_insights.cache_clear()


def _place_payload(**overrides) -> dict:
    image = {
        "sourceUrl": "https://x/1.jpg",
        "sceneHint": "동해 바다가 보이는 해변",
        "moodTags": ["평화로운"],
        "notableFeatures": ["백사장", "커피거리"],
        "lighting": {
            "timeOfDay": "goldenHour",
            "direction": "back-left",
            "angle": "low",
            "colorTemperature": "warm",
            "shadowHardness": "soft",
        },
        "camera": {
            "perspective": "eye-level",
            "horizonPosition": "middle",
            "suggestedFraming": "full-body",
        },
        "placement": {
            "groundPlane": "sand, lower-center",
            "standableSurface": "dry sand, lower-center",
            "suggestedSubjectZone": "center-left",
            "occludingElements": ["울타리"],
        },
        "portraitViability": "high",
        "viabilityReason": "넓은 백사장이 있어 서기 좋다",
        "colorPalette": ["#4a6b3a", "#8fb26e"],
        "season": "summer",
    }
    image.update(overrides)
    return {
        "places": [
            {
                "placeId": "9c1d4f2e-real-uuid",
                "placeName": "안목해변",
                "images": [image],
            }
        ]
    }


def test_load_place_insights_returns_empty_dict_when_file_missing(tmp_path, monkeypatch):
    fake_settings = types.SimpleNamespace(places_dir=tmp_path)
    monkeypatch.setattr("app.places.insights.get_settings", lambda: fake_settings)
    load_place_insights.cache_clear()

    assert load_place_insights() == {}
    assert get_place_insight("anything") is None
    assert get_image_insight("anything", "https://x/1.jpg") is None


def test_load_place_insights_indexes_by_place_id(insights_file):
    insights_file(_place_payload())

    insight = get_place_insight("9c1d4f2e-real-uuid")

    assert insight is not None
    assert insight.place_name == "안목해변"
    assert "백사장" in insight.as_scene_hint()
    assert "평화로운" in insight.as_scene_hint()


def test_get_image_insight_matches_exact_source_url(insights_file):
    payload = _place_payload()
    payload["places"][0]["images"].append(
        {**payload["places"][0]["images"][0], "sourceUrl": "https://x/2.jpg", "season": "winter"}
    )
    insights_file(payload)

    matched = get_image_insight("9c1d4f2e-real-uuid", "https://x/2.jpg")

    assert matched is not None
    assert matched.source_url == "https://x/2.jpg"
    assert matched.season == "winter"


def test_get_image_insight_falls_back_to_first_image_when_url_unmatched(insights_file):
    insights_file(_place_payload())

    matched = get_image_insight("9c1d4f2e-real-uuid", "https://x/does-not-exist.jpg")

    assert matched is not None
    assert matched.source_url == "https://x/1.jpg"


def test_fallback_prefers_a_photo_the_subject_can_actually_stand_in(insights_file):
    """URL이 특정되지 않으면 인물이 설 자리가 있는 사진을 대표로 쓴다."""
    payload = _place_payload(portraitViability="low")
    payload["places"][0]["images"].append(
        {
            **payload["places"][0]["images"][0],
            "sourceUrl": "https://x/2.jpg",
            "portraitViability": "high",
        }
    )
    insights_file(payload)

    assert get_image_insight("9c1d4f2e-real-uuid", None).source_url == "https://x/2.jpg"
    assert get_place_insight("9c1d4f2e-real-uuid").source_url == "https://x/2.jpg"


def test_user_selected_photo_wins_over_viability(insights_file):
    """사용자가 고른 사진은 적합도가 낮아도 그대로 쓴다."""
    payload = _place_payload(portraitViability="low")
    payload["places"][0]["images"].append(
        {
            **payload["places"][0]["images"][0],
            "sourceUrl": "https://x/2.jpg",
            "portraitViability": "high",
        }
    )
    insights_file(payload)

    assert (
        get_image_insight("9c1d4f2e-real-uuid", "https://x/1.jpg").source_url == "https://x/1.jpg"
    )


def test_viable_images_filters_out_unusable_backgrounds(insights_file):
    payload = _place_payload(portraitViability="low")
    payload["places"][0]["images"].append(
        {
            **payload["places"][0]["images"][0],
            "sourceUrl": "https://x/2.jpg",
            "portraitViability": "medium",
        }
    )
    insights_file(payload)

    assert [i.source_url for i in viable_images("9c1d4f2e-real-uuid")] == ["https://x/2.jpg"]


def test_composition_context_stands_subject_on_standable_surface_not_ground(insights_file):
    """바위 해안이 지면이어도 인물은 설 수 있는 표면 위에 세운다."""
    payload = _place_payload()
    payload["places"][0]["images"][0]["placement"] = {
        "groundPlane": "rocky shore, lower-center",
        "standableSurface": "dry sand, lower-left",
        "suggestedSubjectZone": "center-left",
        "occludingElements": [],
    }
    insights_file(payload)

    context = resolve_place_context(
        "9c1d4f2e-real-uuid",
        place_name=None,
        place_region=None,
        place_description=None,
        background_image_url="https://x/1.jpg",
    )

    assert context.ground_plane == "dry sand, lower-left"
    assert "rocky shore" not in context.ground_plane


def test_image_insight_as_lighting_hint_joins_nonempty_values(insights_file):
    insights_file(_place_payload())

    insight = get_image_insight("9c1d4f2e-real-uuid", "https://x/1.jpg")

    assert insight.as_lighting_hint() == "goldenHour, back-left, low, warm, soft"


# ── resolve_place_context 우선순위 통합 ──────────────────────────


def test_resolve_place_context_prefers_insight_over_backend_fields(insights_file):
    insights_file(_place_payload())

    context = resolve_place_context(
        "9c1d4f2e-real-uuid",
        place_name=None,
        place_region="강원특별자치도 강릉시",
        place_description="백엔드가 보낸 짧은 설명",
        background_image_url="https://x/1.jpg",
    )

    assert context.name == "안목해변"
    assert "동해 바다가 보이는 해변" in context.scene_hint
    assert "커피거리" in context.scene_hint
    assert context.scene_hint != "백엔드가 보낸 짧은 설명"
    assert context.light_direction == "back-left"
    assert context.color_temperature == "warm"
    assert context.camera_perspective == "eye-level"
    assert context.subject_zone == "center-left"
    assert context.occluding_elements == "울타리"
    assert context.season == "summer"


def test_resolve_place_context_uses_the_specific_selected_image(insights_file):
    payload = _place_payload()
    payload["places"][0]["images"].append(
        {
            **payload["places"][0]["images"][0],
            "sourceUrl": "https://x/2.jpg",
            "sceneHint": "산책로가 있는 소나무 숲",
            "season": "autumn",
        }
    )
    insights_file(payload)

    context = resolve_place_context(
        "9c1d4f2e-real-uuid",
        place_name=None,
        place_region=None,
        place_description=None,
        background_image_url="https://x/2.jpg",
    )

    assert "산책로가 있는 소나무 숲" in context.scene_hint
    assert context.season == "autumn"


def test_resolve_place_context_falls_back_when_no_insight_matches(monkeypatch):
    monkeypatch.setattr("app.places.backgrounds.get_image_insight", lambda place_id, url: None)

    context = resolve_place_context(
        "no-insight-for-this-place",
        place_name="안목해변",
        place_region=None,
        place_description="백엔드가 보낸 짧은 설명",
    )

    assert context.scene_hint == "백엔드가 보낸 짧은 설명"


# ── resolve_place_context 3순위: 실시간 배경 분석 ─────────────────


def test_resolve_place_context_uses_live_background_analysis_when_cache_misses(
    monkeypatch,
):
    monkeypatch.setattr("app.places.backgrounds.get_dev_place", lambda place_id: None)
    monkeypatch.setattr("app.places.backgrounds.get_image_insight", lambda place_id, url: None)

    analysis = BackgroundAnalysis(
        scene_description="해변가에 늘어선 소나무",
        lighting="노을이 지는 저녁, 따뜻한 색감",
        notable_features=("등대",),
        mood_tags=("고요함",),
    )
    context = resolve_place_context(
        "kto-award:12345",  # Place UUID가 아닌 공모전 수상작 ID
        place_name=None,
        place_region=None,
        place_description="백엔드가 보낸 짧은 설명",
        background_analysis=analysis,
    )

    assert "해변가에 늘어선 소나무" in context.scene_hint
    assert "등대" in context.scene_hint
    assert "고요함" in context.scene_hint
    assert context.lighting_hint == "노을이 지는 저녁, 따뜻한 색감"
    assert context.scene_hint != "백엔드가 보낸 짧은 설명"


def test_resolve_place_context_ignores_empty_live_analysis(monkeypatch):
    monkeypatch.setattr("app.places.backgrounds.get_dev_place", lambda place_id: None)
    monkeypatch.setattr("app.places.backgrounds.get_image_insight", lambda place_id, url: None)

    context = resolve_place_context(
        "kto-gallery:98765",
        place_name=None,
        place_region=None,
        place_description="백엔드가 보낸 짧은 설명",
        background_analysis=BackgroundAnalysis(),  # 분석 실패/빈 응답
    )

    assert context.scene_hint == "백엔드가 보낸 짧은 설명"


def test_has_precomputed_place_context(monkeypatch):
    monkeypatch.setattr("app.places.backgrounds.get_dev_place", lambda place_id: None)
    monkeypatch.setattr("app.places.backgrounds.get_image_insight", lambda place_id, url: None)
    assert has_precomputed_place_context("kto-award:12345") is False

    monkeypatch.setattr(
        "app.places.backgrounds.get_image_insight",
        lambda place_id, url: object(),
    )
    assert has_precomputed_place_context("9c1d4f2e-real-uuid") is True


def test_analysis_from_payload_rejects_aerial_drone_shots():
    """항공샷은 인물을 넣을 수 없다 — 모델이 설 자리를 지어내도 무시한다."""
    analysis = analysis_from_payload(
        {
            "camera": {"perspective": "high-angle", "suggestedFraming": "full-body"},
            "placement": {"standableSurface": "dry sand, lower-left", "suggestedSubjectZone": "c"},
            "sceneAppeal": "high",
        }
    )

    assert analysis["placement"]["standableSurface"] == ""
    assert analysis["placement"]["suggestedSubjectZone"] == ""
    assert analysis["portraitViability"] == "low"


@pytest.mark.parametrize("perspective", ["eye-level", "low-angle"])
def test_analysis_from_payload_keeps_ground_level_viewpoints(perspective):
    analysis = analysis_from_payload(
        {
            "camera": {"perspective": perspective},
            "placement": {"standableSurface": "dry sand", "suggestedSubjectZone": "center"},
            "sceneAppeal": "high",
        }
    )

    assert analysis["placement"]["standableSurface"] == "dry sand"
    assert analysis["portraitViability"] == "high"


def test_context_does_not_fall_back_to_the_unstandable_ground(insights_file):
    """설 자리를 비웠으면 groundPlane(=설 수 없다고 판정한 그 지면)으로 되돌아가면 안 된다."""
    payload = _place_payload()
    payload["places"][0]["images"][0]["placement"] = {
        "groundPlane": "rocky shore, lower-left",
        "standableSurface": "",
        "suggestedSubjectZone": "",
        "occludingElements": [],
    }
    insights_file(payload)

    context = resolve_place_context(
        "9c1d4f2e-real-uuid",
        place_name=None,
        place_region=None,
        place_description=None,
        background_image_url="https://x/1.jpg",
    )

    assert "rocky" not in context.ground_plane


# ── 매력도 축 (3차 배치에서 추가) ────────────────────────────────


def test_standable_but_unattractive_scene_is_not_offered():
    """주차장처럼 설 자리는 넉넉해도 인생샷 배경으로는 못 쓴다."""
    analysis = analysis_from_payload(
        {
            "placement": {"standableSurface": "pavement", "suggestedSubjectZone": "center"},
            "distractions": ["주차된 차량", "라바콘", "안내판"],
            "sceneAppeal": "low",
        }
    )

    # 설 자리는 살아 있어야 한다 — 못 서는 게 아니라 안 예쁜 것이다.
    assert analysis["placement"]["standableSurface"] == "pavement"
    assert analysis["portraitViability"] == "low"
    assert analysis["distractions"] == ["주차된 차량", "라바콘", "안내판"]


def test_attractive_scene_with_nowhere_to_stand_is_not_offered():
    """반대로 아무리 예뻐도 설 자리가 없으면 못 쓴다."""
    analysis = analysis_from_payload(
        {"placement": {"standableSurface": "none"}, "sceneAppeal": "high"}
    )

    assert analysis["portraitViability"] == "low"


@pytest.mark.parametrize("appeal", ["high", "medium"])
def test_viability_follows_scene_appeal_when_standable(appeal):
    analysis = analysis_from_payload(
        {"placement": {"standableSurface": "dry sand"}, "sceneAppeal": appeal}
    )

    assert analysis["portraitViability"] == appeal


# ── 장소별 포즈 가이드 (팀 조사 자료 연동) ────────────────────────


def test_pose_guide_is_attached_by_place_name(insights_file):
    """조사 문서에 있는 장소면 그 장소의 포즈 지침이 붙는다."""
    payload = _place_payload()
    payload["places"][0]["placeName"] = "정동진해변"
    insights_file(payload)

    context = resolve_place_context(
        "9c1d4f2e-real-uuid",
        place_name=None,
        place_region=None,
        place_description=None,
        background_image_url="https://x/1.jpg",
    )

    assert "일출" in context.pose_direction
    assert "태양 위치 변경" in context.pose_negative


def test_pose_guide_is_empty_for_places_not_in_the_research(insights_file):
    """조사 문서에 없는 장소는 빈 값이어야 한다 — 엉뚱한 지침이 붙으면 안 된다."""
    payload = _place_payload()
    payload["places"][0]["placeName"] = "조사되지 않은 장소"
    insights_file(payload)

    context = resolve_place_context(
        "9c1d4f2e-real-uuid",
        place_name=None,
        place_region=None,
        place_description=None,
        background_image_url="https://x/1.jpg",
    )

    assert context.pose_direction == ""
    assert context.pose_negative == ""


def test_pose_guide_resolves_through_alias():
    """조사 문서의 장소명과 백엔드 이름이 다르면 별칭으로 연결된다."""
    from app.places.pose_guides import get_pose_guide

    assert get_pose_guide("구룡폭포(소금강)") is not None
    assert get_pose_guide("오대산 소금강계곡") is not None
    assert get_pose_guide("구룡폭포(소금강)") == get_pose_guide("오대산 소금강계곡")


def test_pose_guide_does_not_partially_match():
    """이름이 겹쳐도 부분 일치로 엉뚱한 지침이 붙으면 안 된다.

    강문해변과 강문솟대다리는 각자 항목을 갖는다 — 앞 두 글자가 같다는 이유로
    다리 지침("다리 중앙을 막지 않는 진입부")이 해변에 붙어서는 안 된다.
    """
    from app.places.pose_guides import get_pose_guide

    beach = get_pose_guide("강문해변")
    bridge = get_pose_guide("강문솟대다리")

    assert beach is not None and bridge is not None
    assert beach != bridge
    # 조사 문서에 없는 이름은 여전히 매칭되지 않아야 한다.
    assert get_pose_guide("강문") is None
    assert get_pose_guide("존재하지 않는 장소") is None


def test_jeongdongjin_area_shares_the_beach_pose_guide():
    """정동진(장소)의 사진이 전부 해변 사진이라 정동진해변 지침을 공유한다."""
    from app.places.pose_guides import get_pose_guide

    assert get_pose_guide("정동진") == get_pose_guide("정동진해변")
    assert "일출" in get_pose_guide("정동진").prompt


def test_place_guidance_wins_over_vlm_framing():
    """조사 지침이 인물 크기를 지정하면 VLM의 프레이밍 판정을 쓰지 않는다."""
    from app.pipeline.prompt import build_composition_prompt
    from app.places.backgrounds import PlaceContext
    from app.schemas.generation import AspectRatio

    conflicted = PlaceContext(
        name="강릉 솔향수목원",
        scene_hint="숲길",
        lighting_hint="오후",
        suggested_framing="half-body",  # VLM 판정
        pose_direction="전신 와이드로 인물은 화면 높이의 25~35퍼센트만 차지한다.",  # 조사 지침
    )
    prompt = build_composition_prompt(conflicted, AspectRatio.PORTRAIT, [])

    assert "Frame the result as half-body" not in prompt
    assert "as the place guidance above specifies" in prompt


def test_vlm_framing_is_used_when_place_guidance_is_silent_on_it():
    from app.pipeline.prompt import build_composition_prompt
    from app.places.backgrounds import PlaceContext
    from app.schemas.generation import AspectRatio

    context = PlaceContext(
        name="어딘가",
        scene_hint="장면",
        lighting_hint="조명",
        suggested_framing="half-body",
        pose_direction="인물은 길 가장자리에서 걷는 순간으로 배치한다.",  # 크기 언급 없음
    )
    prompt = build_composition_prompt(context, AspectRatio.PORTRAIT, [])

    assert "Frame the result as half-body" in prompt


# ── 장면 유형 지침 (단풍 등) ──────────────────────────────────


def test_autumn_foliage_guidance_is_appended_for_foliage_photos(insights_file):
    """단풍이 주피사체인 사진에는 장소 지침 뒤에 단풍 촬영 지침이 붙는다."""
    payload = _place_payload(
        sceneHint="가을의 황금빛 나무들",
        notableFeatures=["황금색 잎", "나무 가지"],
        season="autumn",
    )
    payload["places"][0]["placeName"] = "강릉 경포대"  # 장소 지침이 있는 곳
    insights_file(payload)

    context = resolve_place_context(
        "9c1d4f2e-real-uuid",
        place_name=None,
        place_region=None,
        place_description=None,
        background_image_url="https://x/1.jpg",
    )

    assert "누각" in context.pose_direction  # 장소 지침 유지
    assert "단풍" in context.pose_direction  # 장면 유형 지침 추가
    # 장면 유형이 뒤에 와야 이 사진에 없는 요소를 지목한 장소 지침을 덮는다.
    assert context.pose_direction.index("누각") < context.pose_direction.index("[단풍")
    assert "없는 낙엽길" in context.pose_negative


def test_autumn_scene_without_foliage_does_not_get_foliage_guidance(insights_file):
    """가을에 찍혔어도 단풍이 주피사체가 아니면 붙지 않는다."""
    payload = _place_payload(
        sceneHint="고요하고 아름다운 교회 건물 앞의 풍경",
        notableFeatures=["고딕 양식의 교회", "하늘"],
        season="autumn",
    )
    payload["places"][0]["placeName"] = "임당동 성당"
    insights_file(payload)

    context = resolve_place_context(
        "9c1d4f2e-real-uuid",
        place_name=None,
        place_region=None,
        place_description=None,
        background_image_url="https://x/1.jpg",
    )

    assert "종탑" in context.pose_direction
    assert "단풍" not in context.pose_direction
