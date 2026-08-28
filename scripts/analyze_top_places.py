"""장소 특징 VLM 사전 분석 배치 스크립트.

`docs/adr/0003-place-image-vlm-analysis.md` 참고. 요청 처리 경로와 완전히 분리된
오프라인 도구다 — FastAPI 서비스는 이 스크립트를 임포트하거나 실행 중에 호출하지
않는다.

동작:
    1. 백엔드 REST API(`--backend-base-url`)에서 강릉 장소 목록 + 상세(이미지 포함)를
       가져온다. 이 서비스는 Tour API를 직접 호출하지 않는다 (ADR-0002) — 백엔드가
       이미 정규화한 데이터만 쓴다.
    2. 각 장소의 이미지를 `copyrightCode == "Type1"`(변경 허용)으로만 필터링한다.
    3. `--images-per-place`장 이상 가진 장소만 후보로 남기고(서비스가 장소당
       정확히 그만큼을 쓰기로 했으므로), 그중 이미지가 많은 순으로 상위 N개를
       고른다.
    4. 상위 장소마다 이미지 상한(`--images-per-place`)만큼 다운로드해 Hugging
       Face Inference API(호스팅형, 로컬 RAM/GPU를 쓰지 않는다)로 이미지 1장당
       하나씩 합성용 장면·조명·카메라·인물 배치 정보를 분석한다. 같은 장소라도
       사진마다 구도가 다르므로 이미지별 결과를 합치지 않고 그대로 보존한다.
    5. 결과를 `assets/places/place_insights.json`에 저장한다 — 이 파일이 런타임
       서비스(`app/places/insights.py`)가 읽는 커밋 산출물이다.

실행 예:
    python scripts/analyze_top_places.py \\
        --backend-base-url http://localhost:8080 \\
        --top-n 10 --images-per-place 5

환경변수:
    HF_TOKEN      Hugging Face 액세스 토큰 (HF_ENDPOINT_URL 미설정 시 필수)
    HF_VLM_MODEL  사용할 비전 지원 채팅 모델 (기본값은 --hf-model 참고)
    HF_ENDPOINT_URL
                  설정 시 HF Inference API 대신 이 URL(`POST {url}/analyze`)로
                  호출한다. Colab에서 공개 VLM을 직접 서빙하고 ngrok으로 노출한
                  엔드포인트를 가리키는 용도 — HF_TOKEN 없이 동작한다. 계약은
                  `scripts/colab_vlm_server.ipynb` 참고.
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
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx

logger = logging.getLogger("analyze_top_places")

DEFAULT_HF_MODEL = "Qwen/Qwen2.5-VL-7B-Instruct"
_JSON_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)

ANALYSIS_PROMPT = """You are a scene analyst for an AI photo-composition service that inserts a
person into real tourist-site photos. Analyze the given background image and
return ONLY valid JSON in the schema below. Focus on the information a
compositing model needs to place a person realistically.

Rules:
- "sceneHint", "moodTags", "notableFeatures", "viabilityReason": write in Korean.
- All other fields: use the controlled English values / formats specified.
- Base every value strictly on what is visible. Do not invent objects.

CRITICAL — where a person can actually stand:

- "standableSurface": a flat, walkable surface in this photo where an adult
  could stand on both feet, comfortably, to be photographed. Name the surface
  and its position, e.g. "dry sand, lower-left" or "wooden deck, lower-center".
  Qualifies: dry sand, dirt or paved path, wooden deck/boardwalk, grass, plaza,
  platform, pavement clear of traffic.
  Does NOT qualify: water, surf, wet rocks, boulders or rocky shore, riprap,
  an active roadway, a cliff face, a rooftop edge, or anything a person would
  have to scramble onto. Being merely visible is not enough — a person must be
  able to stand there naturally.
  If nothing in the frame qualifies, return exactly "none".
- "suggestedSubjectZone": must be ON the standableSurface. Give position and
  rough scale, e.g. "center-left, ~40% of frame height". If standableSurface is
  "none", return exactly "none".
- "occludingElements": foreground objects between the camera and that zone that
  would partially cover the person (empty array if the zone is fully open).

CRITICAL — is this a place worth being photographed in:

Judge this SEPARATELY from whether a person can stand here. A parking lot has
plenty of standable ground and is still a bad place for a travel photo.

- "distractions": things that would spoil a travel photo, in Korean. Look for:
  parked cars, roads and traffic cones, signage and information boards, ticket
  booths, power lines and utility poles, construction, apartment blocks, fences,
  railway tracks and overhead wires, a completely blown-out white sky. Empty
  array if the frame is clean.
- "sceneAppeal": would someone want this as the backdrop of their travel photo?
  "high"   = the frame shows what makes this place worth visiting; few or no
             man-made distractions.
  "medium" = pleasant but ordinary, or some distractions at the edges.
  "low"    = distractions dominate the frame (parking, roads, signage, wires,
             buildings), or it is an indoor exhibit / a close-up of an object or
             a sign, or the sky is entirely blown out.
- "viabilityReason": one short Korean sentence explaining the sceneAppeal call.

Schema:
{
  "sceneHint": "<한 줄 한국어 요약>",
  "moodTags": ["<한국어 태그>", "..."],
  "notableFeatures": ["<한국어 요소>", "..."],
  "lighting": {
    "timeOfDay": "dawn | morning | midday | afternoon | goldenHour | dusk | night",
    "direction": "front | back | left | right | back-left | back-right | top | overcast",
    "angle": "low | mid | high",
    "colorTemperature": "warm | neutral | cool",
    "shadowHardness": "hard | soft | none"
  },
  "camera": {
    "perspective": "eye-level | low-angle | high-angle",
    "horizonPosition": "upper | middle | lower",
    "suggestedFraming": "full-body | half-body | close-up"
  },
  "placement": {
    "groundPlane": "<프레임 하단에 실제로 보이는 지면, 예: rocky shore, lower-center>",
    "standableSurface": "<사람이 두 발로 설 수 있는 표면과 위치, 없으면 none>",
    "suggestedSubjectZone": "<standableSurface 위의 위치+대략 크기, 없으면 none>",
    "occludingElements": ["<전경 물체>", "..."]
  },
  "distractions": ["<배경을 해치는 요소>", "..."],
  "sceneAppeal": "high | medium | low",
  "viabilityReason": "<한 줄 한국어 근거>",
  "colorPalette": ["#RRGGBB", "#RRGGBB", "#RRGGBB"],
  "season": "spring | summer | autumn | winter | unknown"
}"""

DEFAULT_ANALYSIS: dict = {
    "sceneHint": "",
    "moodTags": [],
    "notableFeatures": [],
    "lighting": {
        "timeOfDay": "",
        "direction": "",
        "angle": "",
        "colorTemperature": "",
        "shadowHardness": "",
    },
    "camera": {
        "perspective": "",
        "horizonPosition": "",
        "suggestedFraming": "",
    },
    "placement": {
        "groundPlane": "",
        "standableSurface": "",
        "suggestedSubjectZone": "",
        "occludingElements": [],
    },
    "distractions": [],
    "sceneAppeal": "",
    "portraitViability": "",
    "viabilityReason": "",
    "colorPalette": [],
    "season": "unknown",
}

# portraitViability 통제 어휘. 모델이 다른 값을 뱉으면 판정을 신뢰할 수 없으므로
# "low"로 떨어뜨린다 — 모르는 값을 통과시켜 나쁜 배경이 쓰이는 것보다 낫다.
VIABILITY_VALUES = ("high", "medium", "low")

# 사람이 서서 사진을 찍을 수 없는 표면. 프롬프트에 "자격 없음"이라고 명시해도 7B
# 양자화 모델이 부정 조건을 완전히 지키지 못해 `wet rocks`, `rocky shore`, 심지어
# `wooden table`을 설 자리로 답하는 경우가 있어, 코드에서 한 번 더 막는다.
#   - "traffic"은 넣지 않는다: 정상 답변인 "pavement clear of traffic"이 걸린다.
DISQUALIFIED_SURFACES = (
    "rock",
    "boulder",
    "riprap",
    "cliff",
    "water surface",
    "surf",
    "wave",
    "roadway",
    "table",
    "desk",
    "counter",
)


def is_standable(surface: str) -> bool:
    """사람이 두 발로 서서 사진을 찍을 수 있는 표면으로 볼 수 있는지."""
    text = surface.lower()
    return bool(text) and not any(bad in text for bad in DISQUALIFIED_SURFACES)


def is_aerial_view(camera: dict) -> bool:
    """드론 항공샷처럼 인물을 넣을 수 없는 시점인지.

    관광공사 이미지에는 드론 항공샷이 상당수 섞여 있는데(섬·밭·호수 조감도),
    VLM이 여기에 `dry sand`, `paved path` 같은 설 자리를 지어내고 적합도까지
    high로 준다. 실측 결과 이 데이터셋의 `high-angle` 20장은 예외 없이 전부
    항공샷이라, 코드에서 일괄 차단한다.

    한계: `high-angle`은 "약간 높은 곳에서 내려다본 사진"도 포함하는 넓은 값이라
    이 규칙은 그런 정상 사진까지 걸러낼 수 있다. 근본적으로는 분석 스키마에
    "항공/조감 시점인가"를 묻는 필드를 두고 모델이 직접 판정하게 해야 한다.
    """
    return str(camera.get("perspective", "")).strip().lower() == "high-angle"


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
class PlaceInsight:
    place_id: str
    place_name: str
    type1_image_count: int
    analyzed_image_count: int
    images: list[dict]


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


def select_top_places(
    candidates: list[PlaceCandidate], top_n: int, min_images: int = 1
) -> list[PlaceCandidate]:
    """Type1 이미지가 많은 순으로 정렬해 상위 N개를 고른다.

    `min_images`장 미만인 장소는 제외한다 — 서비스가 장소당 정확히 N장을 쓰기로
    했다면, 그만큼 채우지 못하는 장소는 애초에 후보에서 뺀다.
    """
    ranked = sorted(candidates, key=lambda c: len(c.type1_images), reverse=True)
    eligible = [c for c in ranked if len(c.type1_images) >= min_images]
    return eligible[:top_n]


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


def analysis_from_payload(payload: dict) -> dict:
    """VLM 응답 payload를 스키마 기본값(`DEFAULT_ANALYSIS`)과 병합한다.

    모델이 일부 필드를 빠뜨리거나 잘못된 타입을 줘도 항상 스키마와 동일한 모양의
    dict를 돌려준다 — `place_insights.json`에 그대로 직렬화되는 값이라, 다운스트림
    (`app/places/insights.py`)이 키 존재를 가정할 수 있어야 한다.
    """
    lighting = payload.get("lighting") if isinstance(payload.get("lighting"), dict) else {}
    camera = payload.get("camera") if isinstance(payload.get("camera"), dict) else {}
    placement = payload.get("placement") if isinstance(payload.get("placement"), dict) else {}

    standable = normalize_none(placement.get("standableSurface"))
    # 모델이 금지 표면(바위·수면·테이블 등)을 설 자리로 답하면 없는 것으로 본다.
    if not is_standable(standable):
        standable = ""
    # 항공샷에는 애초에 인물을 넣을 수 없다. 모델이 설 자리를 지어내도 무시한다.
    if is_aerial_view(camera):
        standable = ""
    zone = normalize_none(placement.get("suggestedSubjectZone"))
    # 설 자리가 없다고 판정됐으면 인물 위치도 성립하지 않는다. 모델이 둘을
    # 모순되게 답하는 경우가 있어 여기서 강제로 맞춘다.
    if not standable:
        zone = ""

    # 최종 판정은 모델에게 묻지 않고 코드가 두 축에서 합성한다. "설 수 있으면서
    # 예쁜가"를 한 번에 물으면 모델이 앞쪽 조건만 보고 전부 high를 주기 때문이다
    # (주차장·철로·아파트 뷰가 전부 high로 나왔다).
    appeal = str(payload.get("sceneAppeal") or "").strip().lower()
    if appeal not in VIABILITY_VALUES:
        appeal = "low"
    # 설 자리가 없으면 아무리 예뻐도 배경으로 못 쓴다.
    viability = appeal if standable else "low"

    return {
        "sceneHint": str(payload.get("sceneHint", "")),
        "moodTags": [str(v) for v in payload.get("moodTags", []) if v],
        "notableFeatures": [str(v) for v in payload.get("notableFeatures", []) if v],
        "lighting": {key: str(lighting.get(key, "")) for key in DEFAULT_ANALYSIS["lighting"]},
        "camera": {key: str(camera.get(key, "")) for key in DEFAULT_ANALYSIS["camera"]},
        "placement": {
            "groundPlane": str(placement.get("groundPlane", "")),
            "standableSurface": standable,
            "suggestedSubjectZone": zone,
            "occludingElements": [str(v) for v in placement.get("occludingElements", []) if v],
        },
        "distractions": [str(v) for v in payload.get("distractions", []) if v],
        "sceneAppeal": appeal,
        "portraitViability": viability,
        "viabilityReason": str(payload.get("viabilityReason", "")),
        "colorPalette": [str(v) for v in payload.get("colorPalette", []) if v],
        "season": str(payload.get("season") or "unknown"),
    }


def normalize_none(value) -> str:
    """모델이 "none"/"N/A"/빈 값으로 답한 것을 전부 빈 문자열로 통일한다."""
    text = str(value or "").strip()
    return "" if text.lower() in ("", "none", "n/a", "null", "없음") else text


def merge_place_insight(
    place_id: str,
    place_name: str,
    type1_image_count: int,
    analyzed: list[tuple[PlaceImageRef, dict]],
) -> PlaceInsight | None:
    """분석된 이미지들을 장소 리포트 하나로 묶는다.

    이미지마다 조명·카메라·배치 정보가 서로 다르므로(같은 장소라도 사진마다
    구도가 다르다) 하나로 합치지 않는다 — 실서비스가 사용자가 고른 특정 사진의
    데이터로 합성 프롬프트를 짜기 때문에, 이미지별 원본 그대로 보존한다.
    """
    if not analyzed:
        return None

    ordered = sorted(analyzed, key=lambda pair: pair[0].sort_order)
    images = [{"sourceUrl": ref.url, **analysis} for ref, analysis in ordered]

    return PlaceInsight(
        place_id=place_id,
        place_name=place_name,
        type1_image_count=type1_image_count,
        analyzed_image_count=len(images),
        images=images,
    )


def build_report(model: str, source: str, top_n: int, insights: list[PlaceInsight]) -> dict:
    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "source": source,
        "topN": top_n,
        "places": [
            {
                "placeId": insight.place_id,
                "placeName": insight.place_name,
                "type1ImageCount": insight.type1_image_count,
                "analyzedImageCount": insight.analyzed_image_count,
                "images": insight.images,
            }
            for insight in insights
        ],
    }


def load_existing_insights(output_path: Path) -> list[PlaceInsight]:
    """이전 실행이 남긴 리포트에서 분석이 끝난 장소들을 읽어온다.

    파일이 없거나 깨졌으면 빈 리스트 — 이어하기는 최선 노력이지, 실패해서 배치
    전체를 막아서는 안 된다.
    """
    if not output_path.is_file():
        return []
    try:
        raw = json.loads(output_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("기존 리포트를 읽지 못해 이어하기를 건너뛴다: %s", output_path)
        return []

    restored: list[PlaceInsight] = []
    for entry in raw.get("places", []):
        place_id = entry.get("placeId")
        images = entry.get("images") or []
        if not place_id or not images:
            continue
        restored.append(
            PlaceInsight(
                place_id=place_id,
                place_name=entry.get("placeName", ""),
                type1_image_count=entry.get("type1ImageCount", len(images)),
                analyzed_image_count=entry.get("analyzedImageCount", len(images)),
                images=images,
            )
        )
    return restored


def write_report(
    output_path: Path, hf_model: str, source: str, top_n: int, insights: list[PlaceInsight]
) -> dict:
    report = build_report(hf_model, source, top_n, insights)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


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
) -> dict:
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
    return analysis_from_payload({})


def call_custom_endpoint_with_retry(
    http_client: httpx.Client,
    endpoint_url: str,
    image_bytes: bytes,
    mime: str,
    *,
    max_retries: int = 3,
) -> dict:
    """`scripts/colab_vlm_server.ipynb`가 노출하는 `POST {endpoint_url}/analyze`를 호출한다.

    HF Inference API와 계약을 맞추지 않고 자체 JSON 계약을 쓴다(호출부·서버 양쪽을
    이 리포에서 관리하므로). ngrok 콜드 스타트/일시적 502·503도 감안해 재시도한다.
    """
    payload = {
        "image_b64": base64.b64encode(image_bytes).decode(),
        "mime": mime,
        "prompt": ANALYSIS_PROMPT,
        "max_tokens": 500,
    }
    url = f"{endpoint_url.rstrip('/')}/analyze"

    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            response = http_client.post(url, json=payload, timeout=120.0)
            response.raise_for_status()
            text = response.json().get("text", "")
            return analysis_from_payload(parse_vlm_json(text))
        except httpx.HTTPError as exc:
            last_exc = exc
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if attempt == max_retries or status not in (None, 429, 502, 503, 504):
                break
            delay = 5.0 * (2**attempt)
            logger.info(
                "커스텀 VLM 엔드포인트 재시도 (%s초 대기, 사유=%s)", delay, type(exc).__name__
            )
            time.sleep(delay)

    logger.warning("커스텀 VLM 엔드포인트 호출 실패 (%s): %s", url, last_exc)
    return analysis_from_payload({})


# ── 오케스트레이션 ──────────────────────────────────────────


def run(
    *,
    backend_base_url: str,
    top_n: int,
    images_per_place: int,
    hf_model: str,
    hf_token: str,
    hf_endpoint_url: str,
    output_path: Path,
    resume: bool = False,
) -> dict:
    hf_client = None
    if not hf_endpoint_url:
        from huggingface_hub import InferenceClient

        hf_client = InferenceClient(model=hf_model, token=hf_token)

    # Colab 무료 세션은 배치 도중 끊기는 일이 잦다. `--resume`면 이미 분석된 장소를
    # 그대로 살리고 남은 장소만 처리해, 세션이 끊겨도 처음부터 다시 돌리지 않는다.
    done_insights = load_existing_insights(output_path) if resume else []
    done_place_ids = {insight.place_id for insight in done_insights}
    if done_place_ids:
        logger.info("이어하기: 기존 결과 %d개 장소를 유지한다.", len(done_place_ids))

    source = f"colab-ngrok:{hf_endpoint_url}" if hf_endpoint_url else "hf-inference-api"

    with httpx.Client(timeout=30.0) as http_client:
        summaries = fetch_all_places(http_client, backend_base_url)
        candidates = [
            fetch_place_candidate(http_client, backend_base_url, summary) for summary in summaries
        ]
        # 서비스가 장소당 정확히 images_per_place장을 쓰기로 했으므로, 그만큼도
        # 채우지 못하는 장소는 애초에 후보에서 제외한다 (사진 많은 순 top_n곳).
        top_places = select_top_places(candidates, top_n, min_images=images_per_place)
        logger.info(
            "Type1 이미지 %d장 이상 보유 상위 %d개 장소 선정.", images_per_place, len(top_places)
        )

        insights: list[PlaceInsight] = list(done_insights)
        failures = 0
        for candidate in top_places:
            if candidate.place_id in done_place_ids:
                continue
            images = cap_images(candidate.type1_images, images_per_place)
            analyzed: list[tuple[PlaceImageRef, dict]] = []
            for image_ref in images:
                downloaded = download_image(http_client, image_ref.url)
                if downloaded is None:
                    continue
                image_bytes, mime = downloaded
                if hf_endpoint_url:
                    analysis = call_custom_endpoint_with_retry(
                        http_client, hf_endpoint_url, image_bytes, mime
                    )
                else:
                    analysis = call_hf_vlm_with_retry(hf_client, hf_model, image_bytes, mime)
                if analysis["sceneHint"]:
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
            # 장소 하나가 끝날 때마다 저장한다. Colab 세션이 도중에 끊겨도 여기까지의
            # 결과는 파일에 남고, `--resume`으로 남은 장소만 이어서 돌릴 수 있다.
            write_report(output_path, hf_model, source, top_n, insights)

        logger.info("성공 %d / 실패 %d", len(insights), failures)

    report = write_report(output_path, hf_model, source, top_n, insights)
    logger.info("저장 완료: %s", output_path)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend-base-url", required=True, help="백엔드 API base URL")
    parser.add_argument("--top-n", type=int, default=10)
    parser.add_argument("--images-per-place", type=int, default=5)
    parser.add_argument("--hf-model", default=os.environ.get("HF_VLM_MODEL", DEFAULT_HF_MODEL))
    parser.add_argument(
        "--hf-endpoint-url",
        default=os.environ.get("HF_ENDPOINT_URL", ""),
        help="설정 시 HF Inference API 대신 이 URL(POST {url}/analyze)을 호출한다 "
        "(예: Colab+ngrok로 노출한 자체 서빙 엔드포인트). HF_TOKEN 불필요.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "assets" / "places" / "place_insights.json",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="기존 --output 리포트에 이미 있는 장소는 건너뛰고 남은 장소만 분석한다. "
        "Colab 세션이 도중에 끊겼을 때 처음부터 다시 돌리지 않기 위한 옵션.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    hf_token = os.environ.get("HF_TOKEN", "")
    if not args.hf_endpoint_url and not hf_token:
        logger.error("HF_TOKEN 환경변수 또는 --hf-endpoint-url 중 하나가 필요합니다.")
        return 1

    run(
        backend_base_url=args.backend_base_url.rstrip("/"),
        top_n=args.top_n,
        images_per_place=args.images_per_place,
        hf_model=args.hf_model,
        hf_token=hf_token,
        hf_endpoint_url=args.hf_endpoint_url,
        output_path=args.output,
        resume=args.resume,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
