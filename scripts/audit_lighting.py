"""배경 사진의 조명 데이터를 Gemini로 다시 판정한다.

왜 별도 스크립트인가:
    `scripts/analyze_top_places.py`가 쓰는 Qwen2.5-VL-7B(4bit)의 조명 판정이
    사실상 상수였다. 159장 기준으로 `shadowHardness`는 **전부** "soft",
    `angle`은 145장이 "mid", `colorTemperature`는 134장이 "neutral",
    `direction`은 좌우 구분이 1장뿐이었다.

    이 값들이 그대로 합성 프롬프트에 들어가 실제 품질을 망가뜨렸다 — 역광 사진을
    "front"로 적어 인물만 정면광을 받았고, 황금빛 단풍을 "neutral"로 적어 흰 옷이
    순백으로 남았다. `sceneAppeal` 때와 같은 처방을 쓴다: 판정을 Gemini에 맡긴다.

    조명 외 필드(장면·지면·설 자리·매력도)는 건드리지 않는다.

실행:
    python scripts/audit_lighting.py            # place_insights.json 갱신
    python scripts/audit_lighting.py --dry-run  # 저장하지 않고 변경점만 출력
    python scripts/audit_lighting.py --limit 10 # 앞 10장만 (프롬프트 점검용)
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

logger = logging.getLogger("audit_lighting")

DEFAULT_PATH = Path(__file__).resolve().parents[1] / "assets" / "places" / "place_insights.json"

# 판정 결과가 이 집합을 벗어나면 그 필드는 기존 값을 유지한다.
ALLOWED = {
    "timeOfDay": (
        "dawn", "morning", "midday", "afternoon", "goldenHour", "dusk", "night", "unknown",
    ),
    "direction": ("front", "back", "left", "right", "top", "diffuse"),
    "angle": ("low", "mid", "high"),
    "colorTemperature": ("warm", "neutral", "cool"),
    "shadowHardness": ("hard", "soft", "none"),
}

LIGHTING_PROMPT = """You are a lighting analyst for a photo-composition service. A person
will be composited into this photo, and your reading of the light is what tells
the compositor how to light them. Getting it wrong makes the result look pasted.

Work from the evidence in the image, not from what the scene "usually" looks like.

**Find the shadows first.** Locate shadows cast by trees, poles, railings,
buildings or people, and see which way they run relative to the camera.

- Shadows running TOWARD the camera (pointing at the viewer) mean the light is
  behind the subject: `direction` is "back". A dark canopy, dark foreground or
  dark silhouettes against a bright sky is also backlight.
- Shadows running AWAY from the camera mean the light is behind the camera:
  `direction` is "front".
- Shadows running across the frame mean side light: "left" or "right", named by
  the side the light comes FROM.
- An overcast sky with no directional shadows at all is "diffuse".

Then judge the rest from what you see:

- `shadowHardness`: "hard" for crisp, sharply-edged shadows under direct sun —
  this is common on a clear day, so do not default to "soft". "soft" for
  gentle-edged shadows under haze or thin cloud. "none" when overcast leaves no
  cast shadows at all.
- `angle`: "low" when shadows are long relative to what casts them (near sunrise
  or sunset), "high" when they are short and pooled under objects (near midday),
  "mid" otherwise.
- `colorTemperature`: "warm" when the light is golden, amber or orange —
  including autumn foliage scenes and anything near sunrise or sunset. "cool"
  for blue-shifted shade, overcast or twilight. "neutral" only when it is
  genuinely neither.
- `timeOfDay`: read it from the sun height, shadow length and sky colour.

Return ONLY this JSON:
{
  "direction": "front | back | left | right | top | diffuse",
  "shadowHardness": "hard | soft | none",
  "angle": "low | mid | high",
  "colorTemperature": "warm | neutral | cool",
  "timeOfDay": "dawn | morning | midday | afternoon | goldenHour | dusk | night | unknown",
  "evidence": "<한 줄 한국어. 어떤 그림자를 보고 방향을 정했는지>"
}"""


async def read_lighting(provider: GeminiProvider, image: bytes, mime: str) -> dict | None:
    """조명 판정 한 장. 실패하면 None (기존 값을 유지한다)."""
    try:
        payload = await provider._ask_json(image, mime, LIGHTING_PROMPT)
    except Exception as exc:  # noqa: BLE001 - 한 장 실패로 전체를 멈추지 않는다
        logger.warning("조명 판정 실패: %s", type(exc).__name__)
        return None

    verdict = {}
    for field, allowed in ALLOWED.items():
        value = str(payload.get(field) or "").strip()
        # 대소문자만 다른 답(goldenhour)을 버리지 않도록 맞춰본다.
        match = next((a for a in allowed if a.lower() == value.lower()), None)
        if match:
            verdict[field] = match
    if not verdict:
        return None
    verdict["evidence"] = str(payload.get("evidence", ""))
    return verdict


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
    changes: collections.Counter = collections.Counter()

    with httpx.Client(timeout=30.0) as client:
        for place in report["places"]:
            for image in place["images"]:
                if limit is not None and audited >= limit:
                    break
                downloaded = download(client, image["sourceUrl"])
                if downloaded is None:
                    failed += 1
                    continue
                verdict = await read_lighting(provider, *downloaded)
                if verdict is None:
                    failed += 1
                    continue

                lighting = image["lighting"]
                for field in ALLOWED:
                    if field not in verdict:
                        continue
                    if lighting.get(field) != verdict[field]:
                        changes[f"{field}: {lighting.get(field)} -> {verdict[field]}"] += 1
                    lighting[field] = verdict[field]
                lighting["evidence"] = verdict["evidence"]
                audited += 1

            logger.info("판정 완료: %s", place["placeName"])
            if not dry_run:
                path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    report["lightingModel"] = provider.vision_model
    if not dry_run:
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    logger.info("조명 재판정 %d장 / 실패 %d장", audited, failed)
    for label, count in changes.most_common(30):
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
