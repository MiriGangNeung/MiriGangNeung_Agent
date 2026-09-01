"""최종 설정(조명·배치 재판정 + 배경 보존 검사)으로 사용 가능한 장소를 전부 합성한다.

산출물은 test_results/final/ 에 모은다. 이전 라운드들은 옛 데이터로 만든 것이라
그대로 옮기면 '최종 검증'이라는 이름이 사실과 달라진다.
"""
import json
import pathlib
import time

import requests

API = "http://127.0.0.1:8100/v1/generations"
ROOT = pathlib.Path("/home/soborobang1/MiriGangNeung_Agent")
OUT = ROOT / "test_results" / "final"
RANK = {"high": 0, "medium": 1}
TERMINAL = {"DONE", "FAILED", "CANCELED"}


def slugify(name: str) -> str:
    return name.replace(" ", "_").replace("(", "_").replace(")", "").replace("·", "_")


def select():
    data = json.loads((ROOT / "assets/places/place_insights.json").read_text(encoding="utf-8"))
    rows = []
    for place in data["places"]:
        usable = [i for i in place["images"] if i["portraitViability"] in RANK]
        if not usable:
            continue
        usable.sort(key=lambda i: RANK[i["portraitViability"]])
        rows.append((place["placeId"], place["placeName"], usable[0]))
    rows.sort(key=lambda r: RANK[r[2]["portraitViability"]])
    return rows


def fetch(url: str, dest: pathlib.Path) -> pathlib.Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        r = requests.get(url, timeout=60)
        r.raise_for_status()
        dest.write_bytes(r.content)
    return dest


def run(place_id, place_name, image, subject):
    slug = slugify(place_name)
    bg = fetch(image["sourceUrl"], OUT / "backgrounds" / f"{slug}.jpg")
    sub = ROOT / subject
    who = "female" if subject.startswith("woman") else "male"
    dest = OUT / who
    dest.mkdir(parents=True, exist_ok=True)

    # 이미 뽑힌 장소는 건너뛴다 — 레이트 리밋으로 중단된 배치를 이어서 돌릴 수 있다.
    if (dest / f"{slug}.png").exists():
        return {"place": place_name, "who": who, "status": "이미있음",
                "viability": image["portraitViability"],
                "file": str((dest / f"{slug}.png").relative_to(ROOT)),
                "sourceUrl": image["sourceUrl"]}

    with sub.open("rb") as fh, bg.open("rb") as bfh:
        r = requests.post(
            API,
            files={"photo": (sub.name, fh, "image/jpeg"),
                   "background": (bg.name, bfh, "image/jpeg")},
            data={"onePickPlaceId": place_id, "placeName": place_name,
                  "backgroundImageUrl": image["sourceUrl"], "aspectRatio": "4:5",
                  "idempotencyKey": f"final-{slug}-{int(time.time())}"},
            timeout=60,
        )
    if r.status_code != 202:
        return {"place": place_name, "who": who, "status": f"거부 {r.status_code}",
                "detail": r.text[:120]}
    job = r.json()["providerJobId"]

    st, s = None, {}
    for _ in range(75):
        time.sleep(4)
        s = requests.get(f"{API}/{job}", timeout=30).json()
        st = s.get("status")
        if st in TERMINAL:
            break
    if st != "DONE":
        err = s.get("error") or {}
        return {"place": place_name, "who": who, "status": st or "시간초과",
                "detail": err.get("code", "")}

    path = dest / f"{slug}.png"
    path.write_bytes(requests.get(f"{API}/{job}/result", timeout=60).content)
    return {"place": place_name, "who": who, "status": "OK",
            "viability": image["portraitViability"],
            "file": str(path.relative_to(ROOT)),
            "sourceUrl": image["sourceUrl"]}


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    results = []
    for n, (pid, name, img) in enumerate(select()):
        subject = "woman1.jpg" if n % 2 == 0 else "male1.jpeg"
        try:
            row = run(pid, name, img, subject)
        except Exception as exc:  # noqa: BLE001 - 한 건 실패로 배치를 멈추지 않는다
            row = {"place": name, "who": subject, "status": "예외", "detail": str(exc)[:120]}
        results.append(row)
        print(
            f"{row['status']:8s} {row['place']} ({row['who']}) {row.get('detail','')}", flush=True
        )
        (OUT / "manifest.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    ok = sum(1 for r in results if r["status"] == "OK")
    print(f"\n성공 {ok}/{len(results)}")
