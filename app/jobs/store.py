"""Job 상태 저장소.

Redis를 기본으로 쓰고 (백엔드가 이미 Redis를 운용 중), REDIS_HOST가 비었거나 연결에
실패하면 인메모리로 폴백한다. 인메모리는 단일 프로세스 개발·테스트 전용이다.
"""

from __future__ import annotations

import abc
import logging
import threading
from datetime import datetime, timezone

from pydantic import BaseModel, Field

from app.schemas.generation import (
    STAGE_LABELS,
    AspectRatio,
    ErrorPayload,
    GenerationJobResponse,
    GenerationMetadata,
    GenerationResult,
    JobStatus,
    SafetyReport,
    SafetyStatus,
    StyleTag,
    VariationMode,
)

logger = logging.getLogger(__name__)

_KEY_PREFIX = "mirigangneung:ai:job:"
_IDEMPOTENCY_PREFIX = "mirigangneung:ai:idem:"
_BUDGET_PREFIX = "mirigangneung:ai:budget:"
_RATE_PREFIX = "mirigangneung:ai:rate:"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobRecord(BaseModel):
    """저장소에 직렬화되는 Job 전체 상태."""

    provider_job_id: str
    status: JobStatus = JobStatus.QUEUED
    one_pick_place_id: str
    aspect_ratio: AspectRatio
    variation_mode: VariationMode = VariationMode.SAME
    provider: str
    model: str
    prompt_version: str

    # 백엔드 Place 테이블에 이미 있는 정보를 프롬프트 힌트로 활용한다 (선택).
    place_name: str | None = None
    place_region: str | None = None
    place_description: str | None = None

    input_key: str | None = None
    # 제출 시점에 항상 해석되어 채워진다 (실 업로드 / 개발 카탈로그 / mock 플레이스홀더).
    background_key: str | None = None
    result_key: str | None = None
    result_width: int | None = None
    result_height: int | None = None

    safety_status: SafetyStatus = SafetyStatus.UNKNOWN
    safety_reason_code: str | None = None

    error_code: str | None = None
    error_message: str | None = None
    error_retryable: bool | None = None

    style_tags: list[StyleTag] = Field(default_factory=list)
    estimated_cost_usd: float | None = None
    attempts: int = 0

    idempotency_key: str | None = None
    cancelled: bool = False

    created_at: str = Field(default_factory=_now_iso)
    completed_at: str | None = None

    @property
    def duration_ms(self) -> int | None:
        if not self.completed_at:
            return None
        started = datetime.fromisoformat(self.created_at)
        finished = datetime.fromisoformat(self.completed_at)
        return int((finished - started).total_seconds() * 1000)

    def to_response(self, result_url: str | None = None) -> GenerationJobResponse:
        result = None
        if self.status is JobStatus.DONE and self.result_key and result_url:
            result = GenerationResult(
                imageReference=result_url,
                width=self.result_width or 0,
                height=self.result_height or 0,
                aspectRatio=self.aspect_ratio,
            )

        error = None
        if self.error_code:
            error = ErrorPayload(
                code=self.error_code,
                message=self.error_message or "",
                retryable=bool(self.error_retryable),
            )

        return GenerationJobResponse(
            providerJobId=self.provider_job_id,
            status=self.status,
            coarseStatus=self.status.coarse,
            stage=STAGE_LABELS[self.status],
            progress=self.status.progress,
            result=result,
            safety=SafetyReport(status=self.safety_status, reasonCode=self.safety_reason_code),
            error=error,
            metadata=GenerationMetadata(
                provider=self.provider,
                model=self.model,
                promptVersion=self.prompt_version,
                onePickPlaceId=self.one_pick_place_id,
                createdAt=self.created_at,
                completedAt=self.completed_at,
                durationMs=self.duration_ms,
                styleTags=self.style_tags,
                estimatedCostUsd=self.estimated_cost_usd,
                attempts=self.attempts,
            ),
        )


class JobStore(abc.ABC):
    """Job 상태 + 멱등키 + 카운터를 다루는 최소 인터페이스."""

    name: str

    @abc.abstractmethod
    def save(self, record: JobRecord) -> None: ...

    @abc.abstractmethod
    def get(self, provider_job_id: str) -> JobRecord | None: ...

    @abc.abstractmethod
    def find_by_idempotency_key(self, key: str) -> str | None: ...

    @abc.abstractmethod
    def remember_idempotency_key(self, key: str, provider_job_id: str) -> None: ...

    @abc.abstractmethod
    def increment_counter(self, name: str, ttl_seconds: int) -> int: ...


class InMemoryJobStore(JobStore):
    name = "memory"

    def __init__(self, ttl_seconds: int):
        self._ttl = ttl_seconds
        self._jobs: dict[str, str] = {}
        self._idempotency: dict[str, str] = {}
        self._counters: dict[str, int] = {}
        self._lock = threading.Lock()

    def save(self, record: JobRecord) -> None:
        with self._lock:
            self._jobs[record.provider_job_id] = record.model_dump_json()

    def get(self, provider_job_id: str) -> JobRecord | None:
        with self._lock:
            raw = self._jobs.get(provider_job_id)
        return JobRecord.model_validate_json(raw) if raw else None

    def find_by_idempotency_key(self, key: str) -> str | None:
        with self._lock:
            return self._idempotency.get(key)

    def remember_idempotency_key(self, key: str, provider_job_id: str) -> None:
        with self._lock:
            self._idempotency[key] = provider_job_id

    def increment_counter(self, name: str, ttl_seconds: int) -> int:
        with self._lock:
            self._counters[name] = self._counters.get(name, 0) + 1
            return self._counters[name]


class RedisJobStore(JobStore):
    name = "redis"

    def __init__(self, client, ttl_seconds: int):
        self._redis = client
        self._ttl = ttl_seconds

    def save(self, record: JobRecord) -> None:
        self._redis.setex(_KEY_PREFIX + record.provider_job_id, self._ttl, record.model_dump_json())

    def get(self, provider_job_id: str) -> JobRecord | None:
        raw = self._redis.get(_KEY_PREFIX + provider_job_id)
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return JobRecord.model_validate_json(raw)

    def find_by_idempotency_key(self, key: str) -> str | None:
        raw = self._redis.get(_IDEMPOTENCY_PREFIX + key)
        if raw is None:
            return None
        return raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)

    def remember_idempotency_key(self, key: str, provider_job_id: str) -> None:
        self._redis.setex(_IDEMPOTENCY_PREFIX + key, self._ttl, provider_job_id)

    def increment_counter(self, name: str, ttl_seconds: int) -> int:
        pipe = self._redis.pipeline()
        pipe.incr(name)
        pipe.expire(name, ttl_seconds, nx=True)
        value, _ = pipe.execute()
        return int(value)


def budget_counter_key(day: str) -> str:
    return f"{_BUDGET_PREFIX}{day}"


def rate_counter_key(session: str, hour: str) -> str:
    return f"{_RATE_PREFIX}{session}:{hour}"


def build_job_store(redis_host: str, redis_port: int, ttl_seconds: int) -> JobStore:
    if not redis_host:
        logger.info("REDIS_HOST가 비어 있어 인메모리 JobStore를 사용합니다.")
        return InMemoryJobStore(ttl_seconds)
    try:
        import redis as redis_lib

        client = redis_lib.Redis(host=redis_host, port=redis_port, socket_connect_timeout=2)
        client.ping()
        logger.info("Redis JobStore에 연결했습니다 (%s:%s).", redis_host, redis_port)
        return RedisJobStore(client, ttl_seconds)
    except Exception as exc:  # noqa: BLE001 - 연결 실패 시 폴백이 목적
        logger.warning("Redis 연결에 실패해 인메모리 JobStore로 폴백합니다: %s", type(exc).__name__)
        return InMemoryJobStore(ttl_seconds)


__all__ = [
    "JobRecord",
    "JobStore",
    "InMemoryJobStore",
    "RedisJobStore",
    "build_job_store",
    "budget_counter_key",
    "rate_counter_key",
]
