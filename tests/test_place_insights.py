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
    PlaceInsight,
    get_place_insight,
    load_place_insights,
)
from app.providers.base import BackgroundAnalysis  # noqa: E402
from scripts.analyze_top_places import (  # noqa: E402
    ImageAnalysis,
    PlaceCandidate,
    PlaceImageRef,
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
    text = '```json\n{"scene_description": "해변"}\n```'

    assert parse_vlm_json(text) == {"scene_description": "해변"}


def test_parse_vlm_json_returns_empty_dict_on_malformed_input():
    assert parse_vlm_json("이건 JSON이 아님") == {}
    assert parse_vlm_json("") == {}


# ── merge_place_insight ──────────────────────────────────────────


def test_merge_place_insight_uses_primary_scene_and_unions_tags():
    primary_ref = PlaceImageRef(url="primary", title=None, sort_order=0)
    other_ref = PlaceImageRef(url="other", title=None, sort_order=1)
    primary = ImageAnalysis(
        scene_description="해변 풍경",
        lighting="맑은 낮",
        mood_tags=["평화로운"],
        notable_features=["백사장"],
    )
    other = ImageAnalysis(mood_tags=["평화로운", "여름"], notable_features=["소나무"])

    insight = merge_place_insight(
        "place-1",
        "안목해변",
        type1_image_count=8,
        analyzed=[(primary_ref, primary), (other_ref, other)],
    )

    assert insight is not None
    assert insight.scene_hint == "해변 풍경"
    assert insight.lighting_hint == "맑은 낮"
    assert insight.mood_tags == ["평화로운", "여름"]
    assert insight.notable_features == ["백사장", "소나무"]
    assert insight.source_image_urls == ["primary", "other"]
    assert insight.type1_image_count == 8
    assert insight.analyzed_image_count == 2


def test_merge_place_insight_returns_none_when_nothing_analyzed():
    assert merge_place_insight("place-1", "안목해변", type1_image_count=3, analyzed=[]) is None


def test_build_report_shape():
    primary_ref = PlaceImageRef(url="primary", title=None, sort_order=0)
    primary = ImageAnalysis(scene_description="해변", lighting="낮")
    insight = merge_place_insight("place-1", "안목해변", 1, [(primary_ref, primary)])

    report = build_report("some/model", top_n=10, insights=[insight])

    assert report["topN"] == 10
    assert report["model"] == "some/model"
    assert report["places"][0]["placeId"] == "place-1"
    assert report["places"][0]["sceneHint"] == "해변"


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


def test_load_place_insights_returns_empty_dict_when_file_missing(tmp_path, monkeypatch):
    fake_settings = types.SimpleNamespace(places_dir=tmp_path)
    monkeypatch.setattr("app.places.insights.get_settings", lambda: fake_settings)
    load_place_insights.cache_clear()

    assert load_place_insights() == {}
    assert get_place_insight("anything") is None


def test_load_place_insights_indexes_by_place_id(insights_file):
    insights_file(
        {
            "places": [
                {
                    "placeId": "9c1d4f2e-real-uuid",
                    "placeName": "안목해변",
                    "sceneHint": "동해 바다가 보이는 해변",
                    "lightingHint": "맑은 오후 자연광",
                    "moodTags": ["평화로운"],
                    "notableFeatures": ["백사장", "커피거리"],
                }
            ]
        }
    )

    insight = get_place_insight("9c1d4f2e-real-uuid")

    assert insight is not None
    assert insight.place_name == "안목해변"
    assert "백사장" in insight.as_scene_hint()
    assert "평화로운" in insight.as_scene_hint()


def test_place_insight_as_scene_hint_handles_missing_extras():
    insight = PlaceInsight(
        place_id="x", place_name="x", scene_hint="장면 설명", lighting_hint="조명 설명"
    )

    assert insight.as_scene_hint() == "장면 설명"


# ── resolve_place_context 우선순위 통합 ──────────────────────────


def test_resolve_place_context_prefers_insight_over_backend_fields(monkeypatch):
    insight = PlaceInsight(
        place_id="9c1d4f2e-real-uuid",
        place_name="안목해변",
        scene_hint="파도가 부서지는 해변",
        lighting_hint="노을이 지는 저녁",
        mood_tags=("감성적",),
        notable_features=("커피거리",),
    )
    monkeypatch.setattr("app.places.backgrounds.get_place_insight", lambda place_id: insight)

    context = resolve_place_context(
        "9c1d4f2e-real-uuid",
        place_name=None,
        place_region="강원특별자치도 강릉시",
        place_description="백엔드가 보낸 짧은 설명",
    )

    assert context.name == "안목해변"
    assert "파도가 부서지는 해변" in context.scene_hint
    assert "커피거리" in context.scene_hint
    assert context.lighting_hint == "노을이 지는 저녁"
    assert context.scene_hint != "백엔드가 보낸 짧은 설명"


def test_resolve_place_context_falls_back_when_no_insight_matches(monkeypatch):
    monkeypatch.setattr("app.places.backgrounds.get_place_insight", lambda place_id: None)

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
    monkeypatch.setattr("app.places.backgrounds.get_place_insight", lambda place_id: None)

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
    monkeypatch.setattr("app.places.backgrounds.get_place_insight", lambda place_id: None)

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
    monkeypatch.setattr("app.places.backgrounds.get_place_insight", lambda place_id: None)
    assert has_precomputed_place_context("kto-award:12345") is False

    monkeypatch.setattr(
        "app.places.backgrounds.get_place_insight",
        lambda place_id: PlaceInsight(
            place_id=place_id, place_name="x", scene_hint="s", lighting_hint="l"
        ),
    )
    assert has_precomputed_place_context("9c1d4f2e-real-uuid") is True
