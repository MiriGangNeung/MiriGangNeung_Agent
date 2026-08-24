"""장소 특징 VLM 사전 분석 배치 스크립트.

`docs/adr/0003-place-image-vlm-analysis.md` 참고. 요청 처리 경로와 완전히 분리된
오프라인 도구다 — FastAPI 서비스는 이 스크립트를 임포트하거나 실행 중에 호출하지
않는다.

동작:
    1. 백엔드 REST API(`--backend-base-url`)에서 강릉 장소 목록 + 상세(이미지 포함)를
       가져온다. 이 서비스는 Tour API를 직접 호출하지 않는다 (ADR-0002) — 백엔드가
       이미 정규화한 데이터만 쓴다.
    2. 각 장소의 이미지를 `copyrightCode == "Type1"`(변경 허용)으로만 필터링한다.
    3. Type1 이미지가 많은 순으로 상위 N개 장소를 고른다.
    4. 각 장소마다 이미지 상한(`--images-per-place`)만큼 다운로드해 Hugging Face
       Inference API(호스팅형, 로컬 RAM/GPU를 쓰지 않는다)로 장면·조명·분위기를
       분석한다.
    5. 결과를 `assets/places/place_insights.json`에 저장한다 — 이 파일이 런타임
       서비스(`app/places/insights.py`)가 읽는 커밋 산출물이다.

실행 예:
    python scripts/analyze_top_places.py \\
        --backend-base-url http://localhost:8080 \\
        --top-n 10 --images-per-place 5

환경변수:
    HF_TOKEN      Hugging Face 액세스 토큰 (필수)
    HF_VLM_MODEL  사용할 비전 지원 채팅 모델 (기본값은 --hf-model 참고)
"""

from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import httpx

logger = logging.getLogger("analyze_top_places")

DEFAULT_HF_MODEL = "Qwen/Qwen2.5-VL-7B-Instruct"
_JSON_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)

ANALYSIS_PROMPT = """You are analyzing a photo of a real tourist destination for use as
a background reference in an AI photo-compositing service. Describe only what is
visible. Respond with a single JSON object, no prose, no markdown fences:

{
  "scene_description": "1-2 sentences describing the setting (in Korean)",
  "lighting": "time of day, weather, light direction/quality (in Korean)",
  "dominant_colors": ["색1", "색2", "색3"],
  "notable_features": ["눈에 띄는 지형지물/사물 1", "..."],
  "mood_tags": ["분위기 태그 1", "..."]
}"""


# ── 데이터 모델 ──────────────────────────────────────────────


@dataclass(frozen=True)
class PlaceImageRef:
    url: str
    title: str | None
    sort_order: int


@dataclass(frozen=True)
class PlaceCandidate:
    place_id: str
    place_name: str
    type1_images: list[PlaceImageRef]


@dataclass(frozen=True)
class ImageAnalysis:
    scene_description: str = ""
    lighting: str = ""
    dominant_colors: list[str] = field(default_factory=list)
    notable_features: list[str] = field(default_factory=list)
    mood_tags: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PlaceInsight:
    place_id: str
    place_name: str
    type1_image_count: int
    analyzed_image_count: int
    scene_hint: str
    lighting_hint: str
    mood_tags: list[str]
    notable_features: list[str]
    source_image_urls: list[str]


# ── 순수 함수 (네트워크 없음, 테스트 대상) ──────────────────────


def filter_type1_images(images: list[dict]) -> list[PlaceImageRef]:
    """`copyrightCode == "Type1"`(변경 허용)인 이미지만 남긴다.

    Type3(변경금지)는 AI 합성 배경으로 쓸 수 없으므로 여기서 걸러진다.
    """
    result: list[PlaceImageRef] = []
    for image in images:
        if image.get("copyrightCode") != "Type1":
            continue
        url = image.get("imageUrl")
        if not url:
            continue
        result.append(
            PlaceImageRef(
                url=url,
                title=image.get("title"),
                sort_order=image.get("sortOrder") or 0,
            )
        )
    return result


def select_top_places(candidates: list[PlaceCandidate], top_n: int) -> list[PlaceCandidate]:
    """Type1 이미지가 많은 순으로 정렬해 상위 N개를 고른다. 이미지가 없는 장소는 제외."""
    ranked = sorted(candidates, key=lambda c: len(c.type1_images), reverse=True)
    return [c for c in ranked if c.type1_images][:top_n]


def cap_images(images: list[PlaceImageRef], limit: int) -> list[PlaceImageRef]:
    """`sortOrder` 오름차순으로 앞에서부터 최대 `limit`장만 남긴다."""
    return sorted(images, key=lambda i: i.sort_order)[:limit]


def parse_vlm_json(text: str) -> dict:
    """HF 채팅 모델 응답에서 마크다운 코드펜스를 벗기고 JSON을 파싱한다.

    `app/providers/gemini.py`의 `_ask_json` 파싱 패턴과 동일한 방식. 실패하면
    빈 dict를 돌려준다 — 장소 하나의 이미지 하나가 파싱 실패했다고 스크립트
    전체가 죽으면 안 된다.
    """
    stripped = (text or "").strip()
    if not stripped:
        return {}
    try:
        return json.loads(_JSON_FENCE.sub("", stripped).strip())
    except json.JSONDecodeError:
        logger.warning("VLM 응답을 JSON으로 파싱하지 못했습니다.")
        return {}


def analysis_from_payload(payload: dict) -> ImageAnalysis:
    return ImageAnalysis(
        scene_description=str(payload.get("scene_description", "")),
        lighting=str(payload.get("lighting", "")),
        dominant_colors=[str(v) for v in payload.get("dominant_colors", []) if v],
        notable_features=[str(v) for v in payload.get("notable_features", []) if v],
        mood_tags=[str(v) for v in payload.get("mood_tags", []) if v],
    )


def merge_place_insight(
    place_id: str,
    place_name: str,
    type1_image_count: int,
    analyzed: list[tuple[PlaceImageRef, ImageAnalysis]],
) -> PlaceInsight | None:
    """분석된 이미지들을 하나의 장소 리포트로 합친다.

    대표(정렬 순서상 가장 앞선) 이미지의 장면·조명 설명을 주 텍스트로 쓰고,
    나머지 이미지들의 특징·분위기 태그는 중복 제거해 합친다. 별도 요약 LLM
    호출은 넣지 않는다.
    """
    if not analyzed:
        return None

    ordered = sorted(analyzed, key=lambda pair: pair[0].sort_order)
    primary_ref, primary = ordered[0]

    mood_tags: list[str] = []
    notable_features: list[str] = []
    for _, analysis in ordered:
        for tag in analysis.mood_tags:
            if tag not in mood_tags:
                mood_tags.append(tag)
        for feature in analysis.notable_features:
            if feature not in notable_features:
                notable_features.append(feature)

    return PlaceInsight(
        place_id=place_id,
        place_name=place_name,
        type1_image_count=type1_image_count,
        analyzed_image_count=len(ordered),
        scene_hint=primary.scene_description,
        lighting_hint=primary.lighting,
        mood_tags=mood_tags,
        notable_features=notable_features,
        source_image_urls=[ref.url for ref, _ in ordered],
    )


def build_report(model: str, top_n: int, insights: list[PlaceInsight]) -> dict:
    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "topN": top_n,
        "places": [
            {
                "placeId": insight.place_id,
                "placeName": insight.place_name,
                "type1ImageCount": insight.type1_image_count,
                "analyzedImageCount": insight.analyzed_image_count,
                "sceneHint": insight.scene_hint,
                "lightingHint": insight.lighting_hint,
                "moodTags": insight.mood_tags,
                "notableFeatures": insight.notable_features,
                "sourceImageUrls": insight.source_image_urls,
            }
            for insight in insights
        ],
    }


# ── I/O (네트워크) ──────────────────────────────────────────


def fetch_all_places(client: httpx.Client, base_url: str, page_size: int = 100) -> list[dict]:
    places: list[dict] = []
    page = 0
    while True:
        response = client.get(f"{base_url}/api/v1/places", params={"page": page, "size": page_size})
        response.raise_for_status()
        data = response.json()
        content = data.get("content", [])
        places.extend(content)
        if page + 1 >= data.get("totalPages", 0) or not content:
            break
        page += 1
    return places


def fetch_place_candidate(
    client: httpx.Client, base_url: str, place_summary: dict
) -> PlaceCandidate:
    place_id = place_summary["id"]
    response = client.get(f"{base_url}/api/v1/places/{place_id}")
    response.raise_for_status()
    detail = response.json()
    type1_images = filter_type1_images(detail.get("images", []))
    return PlaceCandidate(
        place_id=place_id,
        place_name=detail.get("name", place_summary.get("name", "")),
        type1_images=type1_images,
    )


def download_image(client: httpx.Client, url: str) -> tuple[bytes, str] | None:
    try:
        response = client.get(url, follow_redirects=True, timeout=30.0)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("이미지 다운로드 실패 (%s): %s", type(exc).__name__, url)
        return None
    mime = response.headers.get("content-type", "image/jpeg").split(";")[0].strip()
    return response.content, mime


def call_hf_vlm_with_retry(
    hf_client, model: str, image_bytes: bytes, mime: str, *, max_retries: int = 3
) -> ImageAnalysis:
    """무료 서버리스 추론의 콜드 스타트(503)를 감안한 지수 백오프 재시도."""
    data_uri = f"data:{mime};base64,{base64.b64encode(image_bytes).decode()}"
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": ANALYSIS_PROMPT},
                {"type": "image_url", "image_url": {"url": data_uri}},
            ],
        }
    ]

    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            response = hf_client.chat_completion(messages=messages, model=model, max_tokens=500)
            text = response.choices[0].message.content or ""
            return analysis_from_payload(parse_vlm_json(text))
        except Exception as exc:  # noqa: BLE001 - HF SDK 예외 유형이 버전마다 다름
            last_exc = exc
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if attempt == max_retries or status not in (None, 429, 503):
                break
            delay = 5.0 * (2**attempt)
            logger.info("HF 추론 재시도 (%s초 대기, 사유=%s)", delay, type(exc).__name__)
            time.sleep(delay)

    logger.warning("HF VLM 호출 실패: %s", last_exc)
    return ImageAnalysis()


# ── 오케스트레이션 ──────────────────────────────────────────


def run(
    *,
    backend_base_url: str,
    top_n: int,
    images_per_place: int,
    hf_model: str,
    hf_token: str,
    output_path: Path,
) -> dict:
    from huggingface_hub import InferenceClient

    with httpx.Client(timeout=30.0) as http_client:
        summaries = fetch_all_places(http_client, backend_base_url)
        candidates = [
            fetch_place_candidate(http_client, backend_base_url, summary) for summary in summaries
        ]
        top_places = select_top_places(candidates, top_n)
        logger.info("Type1 이미지 보유 상위 %d개 장소 선정.", len(top_places))

        hf_client = InferenceClient(model=hf_model, token=hf_token)

        insights: list[PlaceInsight] = []
        failures = 0
        for candidate in top_places:
            images = cap_images(candidate.type1_images, images_per_place)
            analyzed: list[tuple[PlaceImageRef, ImageAnalysis]] = []
            for image_ref in images:
                downloaded = download_image(http_client, image_ref.url)
                if downloaded is None:
                    continue
                image_bytes, mime = downloaded
                analysis = call_hf_vlm_with_retry(hf_client, hf_model, image_bytes, mime)
                if analysis.scene_description or analysis.lighting:
                    analyzed.append((image_ref, analysis))

            insight = merge_place_insight(
                candidate.place_id, candidate.place_name, len(candidate.type1_images), analyzed
            )
            if insight is None:
                failures += 1
                logger.warning(
                    "장소 분석 실패, 건너뜀: %s (%s)", candidate.place_name, candidate.place_id
                )
                continue
            insights.append(insight)
            logger.info("분석 완료: %s (%d장)", insight.place_name, insight.analyzed_image_count)

        logger.info("성공 %d / 실패 %d", len(insights), failures)

    report = build_report(hf_model, top_n, insights)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("저장 완료: %s", output_path)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend-base-url", required=True, help="백엔드 API base URL")
    parser.add_argument("--top-n", type=int, default=10)
    parser.add_argument("--images-per-place", type=int, default=5)
    parser.add_argument("--hf-model", default=os.environ.get("HF_VLM_MODEL", DEFAULT_HF_MODEL))
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "assets" / "places" / "place_insights.json",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    hf_token = os.environ.get("HF_TOKEN", "")
    if not hf_token:
        logger.error("HF_TOKEN 환경변수가 필요합니다.")
        return 1

    run(
        backend_base_url=args.backend_base_url.rstrip("/"),
        top_n=args.top_n,
        images_per_place=args.images_per_place,
        hf_model=args.hf_model,
        hf_token=hf_token,
        output_path=args.output,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
