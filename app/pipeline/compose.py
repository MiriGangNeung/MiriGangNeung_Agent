"""합성 호출 오케스트레이션 (요구사항 E1~E4, E8).

재시도 정책 (09_AI_INTEGRATION.md):
- timeout / 일시적 공급자 실패 -> 제한 횟수 재시도
- 안전성 거부 -> 재시도 금지
"""

from __future__ import annotations

import asyncio
import logging

from app.core.errors import AiServiceError
from app.providers.base import (
    CompositionOutput,
    CompositionRequest,
    ImageCompositionProvider,
    ProviderFailure,
    ProviderTimeout,
)

logger = logging.getLogger(__name__)

RETRY_BACKOFF_SECONDS = 2.0


async def compose_with_retry(
    provider: ImageCompositionProvider,
    request: CompositionRequest,
    *,
    timeout_seconds: float,
    max_retries: int,
) -> tuple[CompositionOutput, int]:
    """(결과, 시도 횟수)를 돌려준다."""
    last_error: AiServiceError | None = None

    for attempt in range(1, max_retries + 2):
        try:
            output = await asyncio.wait_for(provider.compose(request), timeout=timeout_seconds)
        except asyncio.TimeoutError:
            last_error = AiServiceError("PROVIDER_TIMEOUT")
        except ProviderTimeout:
            last_error = AiServiceError("PROVIDER_TIMEOUT")
        except ProviderFailure as exc:
            if not exc.retryable:
                raise AiServiceError("PROVIDER_ERROR", str(exc)) from exc
            last_error = AiServiceError("PROVIDER_ERROR", str(exc))
        except Exception as exc:  # noqa: BLE001
            logger.exception("합성 중 예상치 못한 오류가 발생했습니다.")
            raise AiServiceError("INTERNAL_ERROR") from exc
        else:
            if output.provider_safety_blocked:
                # 공급자가 안전성으로 막은 것은 재시도 대상이 아니다.
                raise AiServiceError(
                    "SAFETY_REJECTED_INPUT",
                    "AI 공급자의 안전성 정책에 따라 생성이 거부되었습니다.",
                )
            return output, attempt

        logger.warning("합성 시도 %d/%d 실패 (%s).", attempt, max_retries + 1, last_error.code)
        if attempt <= max_retries:
            await asyncio.sleep(RETRY_BACKOFF_SECONDS * attempt)

    raise last_error or AiServiceError("PROVIDER_ERROR")
