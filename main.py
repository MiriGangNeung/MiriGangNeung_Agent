"""서비스 진입점. `python main.py` 또는 `uvicorn app.main:app` 둘 다 동작한다."""

from __future__ import annotations

import uvicorn

from app.core.config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",  # noqa: S104 - 컨테이너에서 외부 노출이 필요하다
        port=settings.port,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
