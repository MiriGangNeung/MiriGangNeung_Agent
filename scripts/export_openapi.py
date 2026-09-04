"""OpenAPI 스펙을 `docs/openapi.json`으로 내보낸다.

프론트/백엔드가 클라이언트를 손으로 쓰지 않고 생성해 쓸 수 있도록 스펙을 리포에
커밋해 둔다 — 서버를 띄우지 않아도 되고, 스펙이 언제 바뀌었는지 diff로 보인다.

    python scripts/export_openapi.py          # 파일 갱신
    python scripts/export_openapi.py --check  # 최신인지 확인만 (CI용, 다르면 exit 1)

`--check`는 스펙을 바꾸고 파일 갱신을 잊는 것을 막는다. 계약 문서가 코드와
어긋나는 것이 이 서비스에서 가장 비싼 실수라서다.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OUT = ROOT / "docs" / "openapi.json"


def render() -> str:
    # 스펙 생성에 실제 프로바이더 자격증명이 필요하지 않도록 mock으로 고정한다.
    import os

    os.environ.setdefault("AI_PROVIDER", "mock")
    from app.main import app

    return json.dumps(app.openapi(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="갱신하지 않고 최신인지만 확인")
    args = parser.parse_args()

    spec = render()
    if args.check:
        current = OUT.read_text(encoding="utf-8") if OUT.is_file() else ""
        if current != spec:
            print(f"{OUT.relative_to(ROOT)}가 코드와 다릅니다. "
                  "`python scripts/export_openapi.py`로 갱신하세요.", file=sys.stderr)
            return 1
        print(f"{OUT.relative_to(ROOT)} 최신입니다.")
        return 0

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(spec, encoding="utf-8")
    print(f"{OUT.relative_to(ROOT)} 갱신 완료 ({len(spec):,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
