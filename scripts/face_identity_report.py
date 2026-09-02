"""이미 생성해 둔 합성 결과를 로컬에서 채점한다 (API 호출 0, 비용 0).

목적은 두 가지다.

1. **SFace 점수가 사람 판단과 일치하는지 확인.** 일치하지 않으면 이 점수를 재생성
   루프의 판단 근거로 쓸 수 없다. 이 스크립트가 그 분기점이다.
2. `FACE_SIMILARITY_TARGET`을 데이터로 정하기. 얼굴 비율과 유사도를 함께 뽑아
   "얼굴이 작으면 신원이 무너진다"는 가설도 같이 검증한다.

인물 사진은 결과 파일이 어느 폴더(`female`/`male`)에 있는지로 정한다 —
`scripts/final_batch.py`가 그 규칙으로 저장했다.

    python scripts/face_identity_report.py
    python scripts/face_identity_report.py --dir test_results/v5_retest --subject woman1.jpg
"""

from __future__ import annotations

import argparse
import pathlib
import statistics
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.pipeline.face_identity import (  # noqa: E402
    SFACE_REFERENCE_COSINE,
    face_ratio,
    face_similarity,
)

# final_batch.py가 쓴 규칙: female/ 는 woman1, male/ 은 male1으로 합성했다.
SUBJECT_BY_FOLDER = {"female": "woman1.jpg", "male": "male1.jpeg"}


Row = tuple[str, str, float | None, float | None]


def scan(directory: pathlib.Path, forced_subject: str | None) -> list[Row]:
    rows = []
    for path in sorted(directory.rglob("*.png")):
        subject_name = forced_subject or SUBJECT_BY_FOLDER.get(path.parent.name)
        if subject_name is None:
            continue
        subject = ROOT / subject_name
        if not subject.is_file():
            continue
        image = path.read_bytes()
        rows.append(
            (
                str(path.relative_to(ROOT)),
                subject_name,
                face_similarity(subject.read_bytes(), image),
                face_ratio(image),
            )
        )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", default="test_results/final", help="채점할 디렉터리")
    parser.add_argument("--subject", default=None, help="모든 결과에 이 인물 사진을 쓴다")
    args = parser.parse_args()

    directory = ROOT / args.dir
    if not directory.is_dir():
        print(f"{args.dir}가 없습니다.", file=sys.stderr)
        return 1

    print("업로드 인물 사진 자체의 얼굴 비율:")
    subjects = set(SUBJECT_BY_FOLDER.values()) | ({args.subject} if args.subject else set())
    for name in sorted(subjects):
        path = ROOT / name
        if path.is_file():
            ratio = face_ratio(path.read_bytes())
            print(f"  {name:14s} {ratio:.3f}" if ratio else f"  {name:14s} 얼굴 미검출")

    rows = scan(directory, args.subject)
    if not rows:
        print(f"\n{args.dir}에서 채점할 결과를 찾지 못했습니다.")
        return 1

    print(f"\n=== {args.dir} ({len(rows)}장) ===")
    print(f"{'유사도':>7} {'결과얼굴비율':>10}  {'인물':<12} 파일")
    for name, subject, score, ratio in sorted(rows, key=lambda r: (r[2] is None, r[2] or 0)):
        score_text = f"{score:.3f}" if score is not None else "  -  "
        ratio_text = f"{ratio:.3f}" if ratio is not None else "  -  "
        print(f"{score_text:>7} {ratio_text:>10}  {subject:<12} {name}")

    _summary(rows)
    return 0


def _summary(rows) -> None:
    print("\n=== 인물별 요약 ===")
    for subject in sorted({r[1] for r in rows}):
        scores = [r[2] for r in rows if r[1] == subject and r[2] is not None]
        if not scores:
            print(f"  {subject:14s} 판정 가능한 결과 없음")
            continue
        print(
            f"  {subject:14s} n={len(scores):2d}  "
            f"중앙값 {statistics.median(scores):.3f}  "
            f"최소 {min(scores):.3f}  최대 {max(scores):.3f}"
        )

    scored = [r[2] for r in rows if r[2] is not None]
    unscored = len(rows) - len(scored)
    print(f"\n판정 불가(얼굴 미검출) {unscored}장")

    print(f"\n=== 임계값별 통과율 (SFace 기준값 {SFACE_REFERENCE_COSINE}) ===")
    for threshold in (0.20, 0.25, 0.30, SFACE_REFERENCE_COSINE, 0.40, 0.45):
        passed = sum(1 for s in scored if s >= threshold)
        share = passed / len(scored) * 100 if scored else 0.0
        mark = "  <- SFace 기준" if abs(threshold - SFACE_REFERENCE_COSINE) < 1e-9 else ""
        print(f"  {threshold:.3f}  {passed:3d}/{len(scored)}  {share:5.1f}%{mark}")


if __name__ == "__main__":
    raise SystemExit(main())
