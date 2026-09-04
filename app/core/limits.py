"""비용·남용 제어 (검토 총평 §2-7).

- 일별 생성 예산 상한: 반복 생성으로 원가가 폭증하는 것을 막는다.
- 세션/IP 단위 시간당 제한: 비정상 반복 요청 차단.

두 카운터 모두 JobStore의 increment_counter를 쓴다. Redis면 서버 간 공유되고,
인메모리 폴백이면 프로세스 로컬로만 동작한다.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.core.errors import AiServiceError
from app.jobs.store import JobStore, budget_counter_key, rate_counter_key

_DAY_TTL = 2 * 24 * 3600
_HOUR_TTL = 2 * 3600


def enforce_daily_budget(store: JobStore, limit: int) -> None:
    if limit <= 0:
        return
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    used = store.increment_counter(budget_counter_key(day), _DAY_TTL)
    if used > limit:
        raise AiServiceError("BUDGET_EXCEEDED")


def enforce_session_rate_limit(store: JobStore, session: str, limit: int) -> None:
    if limit <= 0 or not session:
        return
    hour = datetime.now(timezone.utc).strftime("%Y%m%d%H")
    used = store.increment_counter(rate_counter_key(session, hour), _HOUR_TTL)
    if used > limit:
        raise AiServiceError(
            "RATE_LIMITED", "시간당 생성 가능 횟수를 초과했습니다. 잠시 후 다시 시도해 주세요."
        )
