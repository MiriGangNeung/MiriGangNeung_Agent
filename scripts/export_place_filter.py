"""`place_insights.json` → 백엔드·프론트가 쓸 장소/사진 노출 필터를 내보낸다.

노션 '배경 사진 VLM 사전 분석 리포트'가 정한 노출 규칙을 코드 한 곳에 고정하는 것이
목적이다. 지금까지 이 규칙은 문서로만 전달돼, 백엔드가 다른 문서(포즈 조사 43곳)를
보고 화이트리스트를 손으로 옮겨 적는 바람에 두 리스트가 어긋나 있었다.

규칙 (셋 다 만족해야 노출):
  1. portraitViability != "low"        — 설 자리가 없거나 배경이 산만한 사진
  2. camera.perspective != "high-angle" — 드론 항공샷. 인물을 넣을 수 있는 시점이 아니다.
     리포트가 "high-angle은 한 건도 없어야 한다, 다시 나타나면 파이프라인을 의심하라"고
     적어둔 값이라, 남아 있으면 걸러낸다.
  3. standableSurface 가 비어 있지 않음  — 두 발로 설 표면이 실제로 있는 사진

쓸 수 있는 사진이 0장인 장소는 목록에서 빠진다.

    python scripts/export_place_filter.py            # 기본 경로에 쓴다
    python scripts/export_place_filter.py --check    # 쓰지 않고 현재 파일과 비교만
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SOURCE = REPO / "assets" / "places" / "place_insights.json"
OUTPUT = REPO / "assets" / "places" / "viable_places.json"

RULES = [
    'portraitViability != "low"',
    'camera.perspective != "high-angle" (드론 항공샷 제외)',
    "placement.standableSurface 가 비어 있지 않을 것",
]


def is_usable(image: dict) -> bool:
    if image.get("portraitViability") not in ("high", "medium"):
        return False
    if (image.get("camera") or {}).get("perspective") == "high-angle":
        return False
    return bool(((image.get("placement") or {}).get("standableSurface") or "").strip())


def build(source: Path) -> dict:
    raw = json.loads(source.read_text(encoding="utf-8"))
    places = []
    for entry in raw.get("places", []):
        usable = [i for i in entry.get("images", []) if is_usable(i)]
        if not usable:
            continue
        places.append(
            {
                "placeName": entry.get("placeName", ""),
                # placeId는 일부러 넣지 않는다. 백엔드 Place.id는 @GeneratedValue(UUID)라
                # DB를 새로 만들 때마다 바뀌어 조인 키로 쓸 수 없다. 이름으로 맞춘다.
                "usableImageCount": len(usable),
                "usableImageUrls": [i.get("sourceUrl", "") for i in usable if i.get("sourceUrl")],
            }
        )
    places.sort(key=lambda p: (-p["usableImageCount"], p["placeName"]))
    return {
        "_source": "assets/places/place_insights.json",
        "_note": "scripts/export_place_filter.py 가 생성한다. 직접 고치지 말 것.",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "rules": RULES,
        "placeCount": len(places),
        "usableImageCount": sum(p["usableImageCount"] for p in places),
        "places": places,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="쓰지 않고 차이만 보고한다")
    parser.add_argument("--out", type=Path, default=OUTPUT)
    args = parser.parse_args()

    data = build(SOURCE)
    print(f"{data['placeCount']}곳 / {data['usableImageCount']}장")

    if args.check:
        if not args.out.exists():
            print(f"✗ {args.out} 없음")
            return 1
        current = json.loads(args.out.read_text(encoding="utf-8"))
        now = {p["placeName"] for p in data["places"]}
        was = {p["placeName"] for p in current.get("places", [])}
        if now == was:
            print("✓ 장소 목록 일치")
            return 0
        print(f"✗ 추가: {sorted(now - was)}\n✗ 삭제: {sorted(was - now)}")
        return 1

    args.out.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"→ {args.out}")
    for p in data["places"]:
        print(f"   {p['placeName']:22s} {p['usableImageCount']}장")
    return 0


if __name__ == "__main__":
    sys.exit(main())
