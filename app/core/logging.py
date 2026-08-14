"""로깅 설정.

요구사항 B5 / 검토 총평 §4: 로그에 이미지 바이트, 원본 파일명, 얼굴 데이터, 개인 사진 URL을
남기지 않는다. 실수로 흘러 들어가는 경우를 대비해 필터에서 한 번 더 막는다.
"""

from __future__ import annotations

import logging
import re

_REDACTED = "[redacted]"

# base64 이미지 데이터 / data URI / 긴 바이너리 문자열
_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"data:image/[a-zA-Z]+;base64,[A-Za-z0-9+/=]+"), _REDACTED),
    (re.compile(r"[A-Za-z0-9+/]{200,}={0,2}"), _REDACTED),
    (re.compile(r"\b[\w\-. ]+\.(?:jpe?g|png|webp|heic)\b", re.IGNORECASE), _REDACTED),
)


class SensitiveDataFilter(logging.Filter):
    """이미지·파일명으로 보이는 문자열을 기록 직전에 지운다."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # 포맷 실패한 레코드는 그대로 흘려보낸다
            return True

        redacted = message
        for pattern, replacement in _PATTERNS:
            redacted = pattern.sub(replacement, redacted)

        if redacted != message:
            record.msg = redacted
            record.args = ()
        return True


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-8s %(name)s | %(message)s"))
    handler.addFilter(SensitiveDataFilter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())

    # uvicorn 액세스 로그에도 같은 필터를 건다.
    for name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True
