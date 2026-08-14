"""오류 코드 테이블.

`retryable`은 백엔드 09_AI_INTEGRATION.md의 retry 규칙을 그대로 코드로 옮긴 것이다.
백엔드가 재시도 여부를 자체 판단하지 않도록 응답에 항상 실어 보낸다.

- timeout / provider temporary failure  -> retryable
- safety rejected                       -> 자동 무한 retry 금지
- invalid user input                    -> retry 금지
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ErrorSpec:
    code: str
    http_status: int
    retryable: bool
    message: str


_SPECS: tuple[ErrorSpec, ...] = (
    # 입력 형식 (B1, B3)
    ErrorSpec("INVALID_IMAGE_FORMAT", 400, False, "지원하지 않는 이미지 형식입니다."),
    ErrorSpec("IMAGE_TOO_LARGE", 413, False, "이미지 용량이 허용 범위를 넘었습니다."),
    ErrorSpec("IMAGE_TOO_MANY_PIXELS", 413, False, "이미지 해상도가 허용 범위를 넘었습니다."),
    # 인물 검사 (B3, B4)
    ErrorSpec("NO_PERSON_DETECTED", 422, False, "사진에서 인물을 찾지 못했습니다."),
    ErrorSpec("MULTIPLE_PERSONS", 422, False, "인물이 한 명인 사진만 사용할 수 있습니다."),
    ErrorSpec("IMAGE_TOO_BLURRY", 422, False, "사진이 흐려 합성에 사용할 수 없습니다."),
    ErrorSpec("FACE_OCCLUDED", 422, False, "얼굴이 가려져 합성에 사용할 수 없습니다."),
    # 안전성 (E5) — 자동 재시도 금지
    ErrorSpec("SAFETY_REJECTED_INPUT", 422, False, "업로드한 사진이 안전성 기준에 맞지 않습니다."),
    ErrorSpec(
        "SAFETY_REJECTED_OUTPUT", 422, False, "생성 결과가 품질·안전성 기준을 통과하지 못했습니다."
    ),
    # 프로바이더 (E8) — 제한 횟수 재시도
    ErrorSpec("PROVIDER_TIMEOUT", 504, True, "AI 생성이 시간 내에 끝나지 않았습니다."),
    ErrorSpec("PROVIDER_ERROR", 502, True, "AI 공급자 오류가 발생했습니다."),
    ErrorSpec("RATE_LIMITED", 429, True, "요청이 너무 많습니다. 잠시 후 다시 시도해 주세요."),
    # 비용 제어
    ErrorSpec("BUDGET_EXCEEDED", 429, False, "오늘 사용할 수 있는 생성 횟수를 모두 소진했습니다."),
    # 기타
    ErrorSpec("INVALID_REQUEST", 400, False, "요청 값이 올바르지 않습니다."),
    ErrorSpec(
        "BACKGROUND_REQUIRED",
        400,
        False,
        "실제 배경 이미지가 없어 합성을 진행할 수 없습니다. background 파일을 함께 보내주세요.",
    ),
    ErrorSpec("UNAUTHORIZED", 401, False, "인증에 실패했습니다."),
    ErrorSpec("JOB_NOT_FOUND", 404, False, "생성 작업을 찾을 수 없습니다."),
    ErrorSpec("JOB_NOT_READY", 409, False, "아직 결과가 준비되지 않았습니다."),
    ErrorSpec("RESULT_EXPIRED", 410, False, "생성 결과가 만료되었습니다."),
    ErrorSpec("INTERNAL_ERROR", 500, True, "내부 오류가 발생했습니다."),
)

ERROR_SPECS: dict[str, ErrorSpec] = {spec.code: spec for spec in _SPECS}

# 안전성 거부는 파이프라인이 safety.status = REJECTED로도 표현해야 하는 코드다.
SAFETY_ERROR_CODES = frozenset({"SAFETY_REJECTED_INPUT", "SAFETY_REJECTED_OUTPUT"})


class AiServiceError(Exception):
    """서비스 전역에서 쓰는 단일 예외. code로 HTTP 상태와 재시도 가능 여부가 결정된다."""

    def __init__(self, code: str, detail: str | None = None):
        spec = ERROR_SPECS.get(code) or ERROR_SPECS["INTERNAL_ERROR"]
        self.spec = spec
        self.code = spec.code
        self.detail = detail
        super().__init__(f"{spec.code}: {detail or spec.message}")

    @property
    def http_status(self) -> int:
        return self.spec.http_status

    @property
    def retryable(self) -> bool:
        return self.spec.retryable

    @property
    def message(self) -> str:
        return self.detail or self.spec.message

    def to_payload(self) -> dict[str, object]:
        return {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
        }
