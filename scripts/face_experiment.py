"""얼굴 보존 개입안들의 통과율을 측정한다.

배경: v5에서 `face_matches_subject` 게이트를 붙여 "잘 만들어진 남의 얼굴"을 잡아낼
수 있게 됐지만, 생성 자체는 여전히 얼굴을 바꾼다. 어떤 개입이 실제로 듣는지는
표본 몇 장으로는 알 수 없어서 — 생성이 확률적이라 같은 입력도 매번 다르다 — 반복
측정이 필요하다.

측정 대상 변형:
    baseline   현행 v5. 인물 사진 + 배경 두 장.
    facecrop   얼굴만 잘라 512px로 확대한 참조 이미지를 한 장 더 넘긴다.
    upscale    인물 사진 전체를 얼굴이 충분히 커지도록 확대해서 넘긴다.
    both       위 둘을 함께.

`upscale`을 따로 두는 이유: 확대는 정보를 새로 만들지 않으므로 원래대로면 효과가
없어야 한다. 그런데도 효과가 있다면 원인은 해상도 자체가 아니라 모델이 얼굴에
배정하는 표현 용량이라는 뜻이고, 그러면 `facecrop`이 옳은 방향이라는 근거가 된다.
효과가 없다면 `facecrop`의 이득도 확대가 아니라 '얼굴만 따로 보여주는 것'에서
온다는 뜻이다. 어느 쪽이든 다음 결정에 쓰인다.

    python scripts/face_experiment.py --repeats 2
    python scripts/face_experiment.py --variants baseline facecrop --subjects woman1.jpg
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import pathlib
import sys
from dataclasses import dataclass

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.pipeline.face_reference import build_face_reference  # noqa: E402
from app.pipeline.prompt import build_composition_prompt  # noqa: E402
from app.places.backgrounds import resolve_place_context  # noqa: E402
from app.providers.base import CompositionRequest  # noqa: E402
from app.providers.gemini import GeminiProvider  # noqa: E402
from app.schemas.generation import AspectRatio  # noqa: E402

OUT = ROOT / "test_results" / "face_experiment"
BACKGROUNDS = ROOT / "test_results" / "final" / "backgrounds"
VARIANTS = ("baseline", "facecrop", "upscale", "both")

# 얼굴이 작게 찍힌 사진과 크게 찍힌 사진을 함께 넣어야 "해상도가 원인"이라는
# 가설이 실제로 갈린다. 얼굴 크기: woman1 66x96, male1 154x218, Eum2 424x490.
DEFAULT_SUBJECTS = ("woman1.jpg", "male1.jpeg", "Eum2.jpg")

# 성격이 다른 배경 두 곳 — 숲(그늘, 인물 작게)과 데크(역광, 난간 가림).
DEFAULT_PLACES = (("송정해변", "송정해변"), ("정동심곡 바다부채길", "정동심곡_바다부채길"))

# upscale 변형에서 얼굴 높이를 최소 이만큼으로 맞춘다.
UPSCALE_TARGET_FACE_PX = 400


@dataclass
class Case:
    variant: str
    subject: str
    place: str
    run: int
    face_ok: bool | None = None
    reason: str | None = None
    notes: str = ""


def _upscaled_subject(data: bytes) -> bytes:
    """얼굴이 UPSCALE_TARGET_FACE_PX 높이가 되도록 사진 전체를 확대한다."""
    import cv2
    import numpy as np

    from app.pipeline.validate import detect_faces

    matrix = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    faces = detect_faces(matrix) if matrix is not None else []
    if not faces:
        return data

    scale = UPSCALE_TARGET_FACE_PX / max(f.h for f in faces)
    if scale <= 1.0:
        return data

    with Image.open(io.BytesIO(data)) as image:
        image = image.convert("RGB").resize(
            (round(image.width * scale), round(image.height * scale)), Image.LANCZOS
        )
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()


async def run_case(provider, insights, case: Case) -> Case:
    place_name, slug = case.place, _slug(case.place)
    row = next(p for p in insights["places"] if p["placeName"].strip() == place_name)
    image = next(i for i in row["images"] if i["portraitViability"] in ("high", "medium"))
    background = (BACKGROUNDS / f"{slug}.jpg").read_bytes()

    subject = (ROOT / case.subject).read_bytes()
    if case.variant in ("upscale", "both"):
        subject = _upscaled_subject(subject)

    face_reference = None
    if case.variant in ("facecrop", "both"):
        built = build_face_reference(subject)
        if built is None:
            case.reason = "FACE_CROP_FAILED"
            return case
        face_reference = built[0]

    context = resolve_place_context(
        row["placeId"], place_name=place_name, place_region=None,
        place_description=None, background_image_url=image["sourceUrl"],
    )
    prompt = build_composition_prompt(
        context, AspectRatio.PORTRAIT, [], with_face_reference=face_reference is not None
    )
    output = await provider.compose(
        CompositionRequest(
            person_image=subject, person_mime="image/png",
            background_image=background, background_mime="image/jpeg",
            prompt=prompt, aspect_ratio=AspectRatio.PORTRAIT,
            face_reference=face_reference,
        )
    )
    if not output.image:
        case.reason = f"BLOCKED:{output.provider_safety_reason}"
        return case

    stem = f"{case.variant}_{pathlib.Path(case.subject).stem}_{slug}_{case.run}"
    (OUT / f"{stem}.png").write_bytes(output.image)

    # 판정에는 항상 **원본** 인물 사진을 넘긴다. 확대본을 넘기면 변형마다 검사
    # 기준이 달라져서 통과율을 비교할 수 없다.
    verdict = await provider.check_quality(
        output.image, output.mime, background, "image/jpeg",
        (ROOT / case.subject).read_bytes(), "image/jpeg",
    )
    case.face_ok = verdict.details.get("face_matches_subject")
    case.reason = verdict.reason_code
    case.notes = str(verdict.details.get("notes", ""))[:60]
    return case


def _slug(name: str) -> str:
    return name.replace(" ", "_").replace("(", "_").replace(")", "").replace("·", "_")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variants", nargs="+", default=list(VARIANTS), choices=VARIANTS)
    parser.add_argument("--subjects", nargs="+", default=list(DEFAULT_SUBJECTS))
    parser.add_argument("--repeats", type=int, default=2, help="같은 조합을 몇 번 반복할지")
    args = parser.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    provider = GeminiProvider(get_settings())
    insights = json.loads(
        (ROOT / "assets/places/place_insights.json").read_text(encoding="utf-8")
    )

    cases = [
        Case(variant=v, subject=s, place=p, run=r)
        for v in args.variants
        for s in args.subjects
        for p, _ in DEFAULT_PLACES
        for r in range(args.repeats)
    ]
    print(f"총 {len(cases)}건 생성합니다.\n", flush=True)

    results: list[Case] = []
    for case in cases:
        try:
            done = await run_case(provider, insights, case)
        except Exception as exc:  # noqa: BLE001 - 한 건 실패로 실험을 멈추지 않는다
            case.reason = f"ERROR:{type(exc).__name__}"
            done = case
        results.append(done)
        mark = {True: "O", False: "X", None: "-"}[done.face_ok]
        print(
            f"  {mark} {done.variant:9s} {done.subject:12s} {done.place:14s} "
            f"#{done.run} {done.reason or ''} {done.notes}",
            flush=True,
        )

    _report(results, args.variants, args.subjects)
    (OUT / "results.json").write_text(
        json.dumps([c.__dict__ for c in results], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return 0


def _report(results: list[Case], variants: list[str], subjects: list[str]) -> None:
    def rate(rows: list[Case]) -> str:
        judged = [r for r in rows if r.face_ok is not None]
        if not judged:
            return "  -  "
        ok = sum(1 for r in judged if r.face_ok)
        return f"{ok}/{len(judged)}"

    width = max(len(s) for s in subjects) + 2
    print("\n=== face_matches_subject 통과율 ===")
    print(f"{'변형':<11}" + "".join(f"{s:<{width}}" for s in subjects) + "전체")
    for variant in variants:
        rows = [r for r in results if r.variant == variant]
        cells = "".join(
            f"{rate([r for r in rows if r.subject == s]):<{width}}" for s in subjects
        )
        print(f"{variant:<11}" + cells + rate(rows))

    print("\n=== 그 외 거부 사유 ===")
    others = [r for r in results if r.reason and r.reason != "FACE_NOT_PRESERVED"]
    if not others:
        print("  없음")
    for row in others:
        print(f"  {row.variant:9s} {row.subject:12s} {row.place:14s} {row.reason}")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
