"""백엔드 계약 스키마.

status 값은 백엔드 `CompositionStatus` enum과 1:1로 정렬한다 (새 값을 만들지 않는다).
`coarseStatus`는 09_AI_INTEGRATION.md의 축약형(RUNNING|DONE|FAILED)이며, 두 문서가
어긋나지 않도록 함께 실어 보낸다.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    QUEUED = "QUEUED"
    ANALYZING = "ANALYZING"
    COMPOSITING = "COMPOSITING"
    QUALITY_CHECK = "QUALITY_CHECK"
    DONE = "DONE"
    FAILED = "FAILED"

    @property
    def is_terminal(self) -> bool:
        return self in (JobStatus.DONE, JobStatus.FAILED)

    @property
    def coarse(self) -> str:
        if self is JobStatus.DONE:
            return "DONE"
        if self is JobStatus.FAILED:
            return "FAILED"
        return "RUNNING"

    @property
    def progress(self) -> int:
        return _PROGRESS[self]


_PROGRESS: dict[JobStatus, int] = {
    JobStatus.QUEUED: 0,
    JobStatus.ANALYZING: 25,
    JobStatus.COMPOSITING: 55,
    JobStatus.QUALITY_CHECK: 80,
    JobStatus.DONE: 100,
    JobStatus.FAILED: 100,
}

# 프론트엔드 '합성 단계 타임라인'(UI 설계서 3번 섹션)에 그대로 노출되는 한국어 문구
STAGE_LABELS: dict[JobStatus, str] = {
    JobStatus.QUEUED: "요청 접수",
    JobStatus.ANALYZING: "사진과 배경 분석 중",
    JobStatus.COMPOSITING: "이미지 합성 중",
    JobStatus.QUALITY_CHECK: "안전성 및 품질 확인 중",
    JobStatus.DONE: "완료",
    JobStatus.FAILED: "실패",
}


class SafetyStatus(str, Enum):
    PASSED = "PASSED"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"


class AspectRatio(str, Enum):
    """요구사항 E4: SNS에 적합한 비율."""

    SQUARE = "1:1"
    PORTRAIT = "4:5"
    STORY = "9:16"

    @property
    def wh(self) -> tuple[int, int]:
        return _RATIO_WH[self]


_RATIO_WH: dict[AspectRatio, tuple[int, int]] = {
    AspectRatio.SQUARE: (1, 1),
    AspectRatio.PORTRAIT: (4, 5),
    AspectRatio.STORY: (9, 16),
}


class VariationMode(str, Enum):
    """요구사항 E4: '허용된 횟수 내에서 구도나 분위기를 변경해 다시 생성'.

    UI 설계서 재생성 버튼의 두 옵션 중 '다른 배경 선택'은 onePickPlaceId/background를
    바꿔 다시 요청하면 되므로 이미 지원된다. 이 값은 나머지 옵션인
    '구도, 스타일만 살짝 조정'에 대응한다.
    """

    SAME = "same"
    NEW_POSE = "new_pose"
    NEW_MOOD = "new_mood"


class StyleTag(BaseModel):
    """요구사항 B6: 태그 + 신뢰도 점수."""

    category: str
    value: str
    confidence: float = Field(ge=0.0, le=1.0)


class GenerationResult(BaseModel):
    imageReference: str
    width: int
    height: int
    aspectRatio: AspectRatio


class SafetyWarning(BaseModel):
    """결과를 막지는 않지만 사용자에게 알려야 하는 품질 문제."""

    code: str
    message: str


class SafetyReport(BaseModel):
    status: SafetyStatus = SafetyStatus.UNKNOWN
    reasonCode: str | None = None
    # 결과는 정상 제공하되 프론트가 사용자에게 알려야 하는 것들. 선택 필드라
    # 기존 백엔드 연동은 이 값을 무시해도 그대로 동작한다.
    warnings: list[SafetyWarning] = Field(default_factory=list)


class ErrorPayload(BaseModel):
    code: str
    message: str
    retryable: bool


class GenerationMetadata(BaseModel):
    """요구사항 E9: 생성 이력에 남겨야 하는 값들."""

    provider: str
    model: str
    promptVersion: str
    onePickPlaceId: str
    createdAt: str
    completedAt: str | None = None
    durationMs: int | None = None
    styleTags: list[StyleTag] = Field(default_factory=list)
    estimatedCostUsd: float | None = None
    attempts: int = 0


class GenerationJobResponse(BaseModel):
    providerJobId: str
    status: JobStatus
    coarseStatus: str
    stage: str
    progress: int
    result: GenerationResult | None = None
    safety: SafetyReport = Field(default_factory=SafetyReport)
    error: ErrorPayload | None = None
    metadata: GenerationMetadata


class ErrorCodeSpec(BaseModel):
    """`error.code` 하나의 계약. 백엔드가 재시도 여부를 자체 판단하지 않게 한다."""

    code: str
    httpStatus: int
    retryable: bool
    message: str


class SafetyReasonSpec(BaseModel):
    """`safety.reasonCode` 하나와 사용자에게 보일 문구.

    `severity`가 `warn`이면 결과를 막지 않고 `safety.warnings`로만 전달된다.
    `reject`면 Job이 `SAFETY_REJECTED_OUTPUT`으로 실패한다.
    """

    code: str
    message: str
    severity: str = "reject"


class MetaResponse(BaseModel):
    provider: str
    imageModel: str
    visionModel: str
    promptVersion: str
    supportedAspectRatios: list[AspectRatio]
    maxUploadBytes: int
    resultTtlSeconds: int
    # 아래 두 목록은 프론트/백엔드가 화면 문구와 재시도 정책을 자기 쪽에 다시
    # 하드코딩하지 않도록 서버가 그대로 내보내는 카탈로그다. 부팅 시 한 번 읽어
    # 캐시하면 된다.
    errorCodes: list[ErrorCodeSpec]
    safetyReasonCodes: list[SafetyReasonSpec]
    # 얼굴 신원이 살아날 때까지 합성을 다시 시도하는 최대 횟수. 백엔드가 폴링
    # 타임아웃을 잡을 때 쓴다 — 이 값이 크면 한 Job이 그만큼 오래 걸린다.
    faceRegenerateMaxAttempts: int = 1


class HealthResponse(BaseModel):
    status: str
    jobStore: str
    provider: str
