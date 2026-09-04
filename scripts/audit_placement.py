"""배경 사진의 인물 배치 데이터를 Gemini로 다시 판정한다.

왜 별도 스크립트인가:
    `scripts/analyze_top_places.py`가 쓰는 Qwen2.5-VL-7B(4bit)의 배치 판정이
    조명과 마찬가지로 사실상 템플릿이었다. 159장 기준으로 `occludingElements`는
    **전부** 빈 배열, `standableSurface`는 46장이 똑같이 "dry sand, lower-left"
    (산 능선인 안반데기와 숲인 대관령박물관까지 "마른 모래"로 적혔다),
    `suggestedSubjectZone`은 41장이 완전히 동일한 문자열이었다.

    그 결과 사람이 설 수 없는 습지·연꽃밭이 사용 가능으로 분류되고, 합성 모델이
    없는 지면을 지어내는 문제가 생겼다. `sceneAppeal`·조명 때와 같은 처방을 쓴다.

    장면 설명·조명·매력도는 건드리지 않는다. 배치가 바뀌면 `portraitViability`만
    두 축(설 자리 × 매력도)에서 다시 계산한다.

실행:
    python scripts/audit_placement.py            # place_insights.json 갱신
    python scripts/audit_placement.py --dry-run  # 저장하지 않고 변경점만 출력
    python scripts/audit_placement.py --limit 10 # 앞 10장만 (프롬프트 점검용)
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import json
import logging
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.providers.gemini import GeminiProvider  # noqa: E402

logger = logging.getLogger("audit_placement")

DEFAULT_PATH = Path(__file__).resolve().parents[1] / "assets" / "places" / "place_insights.json"
VIABILITY_VALUES = ("high", "medium", "low")

PLACEMENT_PROMPT = """You are deciding where a real person could be placed in this photo.
A tourist's portrait will be composited into it. If you say a person can stand
somewhere they actually cannot, the compositor invents fake ground and the
result is unusable — so be conservative.

Answer from what is actually visible in THIS photo. Do not assume a beach has
sand or a park has a lawn unless you can see it.

**standableSurface** — describe the real, flat, safe, walkable surface a visitor
could put both feet on, and where it is in the frame (e.g. "wooden deck,
lower-right", "paved plaza, center"). Use an EMPTY STRING when there is none:

- the photo is a close-up or macro of leaves, flowers, food, a sign or an object,
  with no usable ground in frame
- the foreground is water, surf, a wetland, a lotus or reed bed, mudflat, or
  marsh
- the ground is loose or wet rock, boulders, riprap, or a cliff edge
- it is an aerial or drone view looking down from far above
- the only open ground is an active roadway, railway track, or parking lot
- the frame is filled by a building, an interior exhibit, or foliage with no floor

**suggestedSubjectZone** — where to place them and how much of the frame height
they should fill, e.g. "lower-left, ~30% of frame height". Keep them off the
landmark and off any text in the photo. Empty string when standableSurface is
empty.

**occludingElements** — things genuinely in the FOREGROUND, between the camera
and where the person would stand, that would naturally overlap them (a railing,
tall grass, a branch, a low wall). Empty array if the spot is unobstructed —
most photos are.

Return ONLY this JSON:
{
  "standableSurface": "<설명 또는 빈 문자열>",
  "suggestedSubjectZone": "<설명 또는 빈 문자열>",
  "occludingElements": ["<전경 요소>", "..."],
  "reason": "<한 줄 한국어 근거>"
}"""


async def read_placement(provider: GeminiProvider, image: bytes, mime: str) -> dict | None:
    """배치 판정 한 장. 실패하면 None (기존 값을 유지한다)."""
    try:
        payload = await provider._ask_json(image, mime, PLACEMENT_PROMPT)
    except Exception as exc:  # noqa: BLE001 - 한 장 실패로 전체를 멈추지 않는다
        logger.warning("배치 판정 실패: %s", type(exc).__name__)
        return None

    if "standableSurface" not in payload:
        return None

    surface = str(payload.get("standableSurface") or "").strip()
    zone = str(payload.get("suggestedSubjectZone") or "").strip()
    # 설 자리가 없다고 판정했으면 배치 구역도 의미가 없다.
    if not surface:
        zone = ""
    return {
        "standableSurface": surface,
        "suggestedSubjectZone": zone,
        "occludingElements": [str(v) for v in payload.get("occludingElements", []) if v],
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


async def run(path: Path, dry_run: bool, limit: int | None) -> None:
    report = json.loads(path.read_text(encoding="utf-8"))
    provider = GeminiProvider(get_settings())

    audited = failed = 0
    flips: collections.Counter = collections.Counter()

    with httpx.Client(timeout=30.0) as client:
        for place in report["places"]:
            for image in place["images"]:
                if limit is not None and audited >= limit:
                    break
                downloaded = download(client, image["sourceUrl"])
                if downloaded is None:
                    failed += 1
                    continue
                verdict = await read_placement(provider, *downloaded)
                if verdict is None:
                    failed += 1
                    continue

                placement = image["placement"]
                was_standable = bool(placement.get("standableSurface"))
                now_standable = bool(verdict["standableSurface"])
                if was_standable != now_standable:
                    flips["설 자리 생김" if now_standable else "설 자리 없음으로 정정"] += 1

                placement["standableSurface"] = verdict["standableSurface"]
                placement["suggestedSubjectZone"] = verdict["suggestedSubjectZone"]
                placement["occludingElements"] = verdict["occludingElements"]
                placement["reason"] = verdict["reason"]

                # 두 축을 다시 합성한다: 아무리 예뻐도 설 자리가 없으면 못 쓴다.
                appeal = str(image.get("sceneAppeal") or "low").strip().lower()
                if appeal not in VIABILITY_VALUES:
                    appeal = "low"
                before = image.get("portraitViability")
                image["portraitViability"] = appeal if now_standable else "low"
                if before != image["portraitViability"]:
                    flips[f"등급 {before} -> {image['portraitViability']}"] += 1
                audited += 1

            logger.info("판정 완료: %s", place["placeName"])
            if not dry_run:
                path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    report["placementModel"] = provider.vision_model
    if not dry_run:
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    logger.info("배치 재판정 %d장 / 실패 %d장", audited, failed)
    for label, count in flips.most_common(20):
        logger.info("  %4d  %s", count, label)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", type=Path, default=DEFAULT_PATH)
    parser.add_argument("--dry-run", action="store_true", help="저장하지 않고 변경점만 본다")
    parser.add_argument("--limit", type=int, default=None, help="앞 N장만 판정한다")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(run(args.path, args.dry_run, args.limit))
    return 0


if __name__ == "__main__":
    sys.exit(main())
