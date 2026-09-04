"""X-API-Key 인증. 백엔드 .env의 AI_API_KEY와 같은 값을 공유한다."""

from __future__ import annotations

import hmac

from fastapi import Header

from app.core.config import get_settings
from app.core.errors import AiServiceError


async def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    settings = get_settings()
    if not settings.auth_enabled:
        return
    if x_api_key is None or not hmac.compare_digest(x_api_key, settings.ai_api_key):
        raise AiServiceError("UNAUTHORIZED")
