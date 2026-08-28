"""배경 사진의 '인생샷 배경으로서의 매력도'를 Gemini로 재평가한다.

왜 별도 스크립트인가:
    `scripts/analyze_top_places.py`가 쓰는 Qwen2.5-VL-7B(4bit)는 "무엇이 보이는가"
    (장면·조명·지면·설 자리)는 잘 뽑아내지만 "이게 좋은 배경인가"라는 미적 판단은
    하지 못했다. 프롬프트에 주차 차량·전선·안내판을 구체적으로 나열하고 판정 축을
    분리해서 두 번 시도했지만, 159장 중 방해 요소를 하나도 찾아내지 못했다
    (스스로 "전기 기둥이 있는"이라고 써놓고도 방해 요소는 빈 배열로 답했다).

    그래서 미적 판단만 떼어내 Gemini(합성 파이프라인이 이미 쓰는 모델)에 맡긴다.
    설 자리·항공샷 판정은 기존 결과를 그대로 유지하고, `sceneAppeal`/`distractions`
    만 덮어쓴 뒤 최종 `portraitViability`를 두 축에서 다시 합성한다.

실행:
    python scripts/rate_scene_appeal.py            # assets/places/place_insights.json 갱신
    python scripts/rate_scene_appeal.py --dry-run  # 저장하지 않고 결과만 출력
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.providers.gemini import GeminiProvider  # noqa: E402

logger = logging.getLogger("rate_scene_appeal")

DEFAULT_PATH = Path(__file__).resolve().parents[1] / "assets" / "places" / "place_insights.json"
APPEAL_VALUES = ("high", "medium", "low")

APPEAL_PROMPT = """You are curating background photos for a service that composites a
tourist's portrait into a real photo of a Gangneung travel spot.

Judge ONLY one thing: would someone actually want this photo as the backdrop of
their own travel portrait? Ignore whether a person could physically stand here —
that is judged separately.

Be strict. Most tourism-archive photos are documentation, not portrait
backdrops. A photo can be a fine landscape and still be a bad backdrop.

Mark it down for anything that would spoil a personal travel photo:
parked cars, roads, traffic cones, information boards and signage, ticket
booths, power lines and utility poles, overhead railway wires, railway tracks,
construction, apartment or office blocks, litter bins, safety barriers, a
completely blown-out white sky, or a frame that is mostly empty pavement.

Return ONLY this JSON:
{
  "distractions": ["<눈에 띄는 방해 요소를 한국어로>", "..."],
  "sceneAppeal": "high | medium | low",
  "reason": "<한 줄 한국어 근거>"
}

"high"   = the frame shows what makes this place worth visiting, and is clean
           of the distractions above.
"medium" = pleasant but ordinary, or distractions sit at the edges.
"low"    = distractions take up a meaningful part of the frame, or it is an
           indoor exhibit, a close-up of an object or sign, or a documentation
           shot rather than a scenic one."""


async def rate_image(provider: GeminiProvider, image: bytes, mime: str) -> dict | None:
    """이미지 한 장의 매력도를 판정한다. 실패하면 None (기존 값을 유지한다)."""
    try:
        payload = await provider._ask_json(image, mime, APPEAL_PROMPT)
    except Exception as exc:  # noqa: BLE001 - 한 장 실패로 전체를 멈추지 않는다
        logger.warning("매력도 판정 실패: %s", type(exc).__name__)
        return None

    appeal = str(payload.get("sceneAppeal") or "").strip().lower()
    if appeal not in APPEAL_VALUES:
        return None
    return {
        "sceneAppeal": appeal,
        "distractions": [str(v) for v in payload.get("distractions", []) if v],
        "reason": str(payload.get("reason", "")),
    }


def download(client: httpx.Client, url: str) -> tuple[bytes, str] | None:
    try:
        response = client.get(url, follow_redirects=True, timeout=30.0)
        response.raise_for_status()
    except httpx.HTTPError:
        logger.warning("이미지 다운로드 실패: %s", url)
        return None
    mime = response.headers.get("content-type", "image/jpeg").split(";")[0].strip()
    return response.content, mime


async def run(path: Path, dry_run: bool) -> None:
    report = json.loads(path.read_text(encoding="utf-8"))
    provider = GeminiProvider(get_settings())

    rated = failed = 0
    with httpx.Client(timeout=30.0) as client:
        for place in report["places"]:
            for image in place["images"]:
                downloaded = download(client, image["sourceUrl"])
                if downloaded is None:
                    failed += 1
                    continue
                verdict = await rate_image(provider, *downloaded)
                if verdict is None:
                    failed += 1
                    continue

                image["sceneAppeal"] = verdict["sceneAppeal"]
                image["distractions"] = verdict["distractions"]
                image["viabilityReason"] = verdict["reason"]
                # 설 자리가 없으면 아무리 예뻐도 못 쓴다 — 두 축을 여기서 합성한다.
                standable = bool(image["placement"].get("standableSurface"))
                image["portraitViability"] = verdict["sceneAppeal"] if standable else "low"
                rated += 1

            logger.info("판정 완료: %s (%d장)", place["placeName"], len(place["images"]))
            if not dry_run:
                path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    report["sceneAppealModel"] = provider.vision_model
    if not dry_run:
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("매력도 판정 %d장 / 실패 %d장", rated, failed)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", type=Path, default=DEFAULT_PATH)
    parser.add_argument("--dry-run", action="store_true", help="저장하지 않고 판정만 해본다")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(run(args.path, args.dry_run))
    return 0


if __name__ == "__main__":
    sys.exit(main())
