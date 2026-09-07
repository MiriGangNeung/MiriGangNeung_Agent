"""생성 결과 안전성·품질 검사 (요구사항 E5).

정책상 중요한 두 가지:
1. 검사에 걸린 결과는 사용자에게 제공하지 않는다.
2. 안전성 거부는 자동 재시도 대상이 아니다 (09_AI_INTEGRATION.md).
   따라서 여기서 던지는 오류의 retryable은 errors.py에서 false로 고정돼 있다.

검사기 자체가 실패한 경우(네트워크 오류 등)는 '거부'가 아니라 UNKNOWN으로 처리하고
결과를 통과시킨다. 검사기 장애로 정상 결과를 버리면 사용자 경험이 더 나빠지고,
공급자 자체 안전 필터가 이미 1차 방어선이기 때문이다.
"""

from __future__ import annotations

import logging

from app.core.errors import AiServiceError
from app.providers.base import ImageCompositionProvider, QualityVerdict
from app.schemas.generation import SafetyStatus

logger = logging.getLogger(__name__)


# 결과를 막지 않고 경고로만 전달하는 사유.
#
# `FACE_NOT_PRESERVED`가 여기 있는 이유: 얼굴이 화면에서 작게 찍힌 사진은 흔한 여행
# 사진인데, 그걸 이유로 결과를 아예 못 받게 하면 정상 사용자가 대량으로 막힌다.
# 얼굴이 조금 다를 수 있다고 알려주고 다시 만들 기회를 주는 편이 낫다.
WARNING_REASON_CODES = frozenset({"FACE_NOT_PRESERVED"})

# 경고로 나갈 때 쓰는 문구. 거부 문구("제공할 수 없습니다")를 그대로 쓰면 결과를 받은
# 사용자에게 앞뒤가 맞지 않는다.
WARNING_MESSAGES: dict[str, str] = {
    "FACE_NOT_PRESERVED": (
        "얼굴이 실제 모습과 조금 다르게 표현됐을 수 있습니다. "
        "마음에 들지 않으면 다시 만들어 보세요."
    ),
}


def warning_for(reason_code: str) -> tuple[str, str]:
    """(코드, 사용자 문구). 경고 사유가 아니면 호출하지 않는다."""
    return reason_code, WARNING_MESSAGES.get(reason_code, DEFAULT_REASON_MESSAGE)


async def check_output(
    provider: ImageCompositionProvider,
    image: bytes,
    mime: str,
    background: bytes | None = None,
    background_mime: str | None = None,
    subject: bytes | None = None,
    subject_mime: str | None = None,
) -> tuple[SafetyStatus, str | None]:
    """통과하면 (PASSED, None), 거부면 AiServiceError를 던진다.

    `background`를 주면 검사기가 원본 배경과 비교해 보존 여부까지 보고,
    `subject`(업로드 인물 사진)까지 주면 얼굴이 그 사람인지도 본다.
    """
    try:
        verdict: QualityVerdict = await provider.check_quality(
            image, mime, background, background_mime, subject, subject_mime
        )
    except Exception as exc:  # noqa: BLE001 - 검사기 장애는 거부가 아니다
        logger.warning("품질 검사기 호출 실패, UNKNOWN으로 통과시킵니다: %s", type(exc).__name__)
        return SafetyStatus.UNKNOWN, None

    if verdict.passed:
        return SafetyStatus.PASSED, None

    if verdict.reason_code in WARNING_REASON_CODES:
        # 거부가 아니라 경고다. 결과는 그대로 제공하고 호출부가 경고를 싣는다.
        logger.info("생성 결과에 품질 경고를 답니다 (reason=%s).", verdict.reason_code)
        return SafetyStatus.PASSED, verdict.reason_code

    logger.info("생성 결과가 품질·안전성 검사에서 거부됐습니다 (reason=%s).", verdict.reason_code)
    raise AiServiceError(
        "SAFETY_REJECTED_OUTPUT",
        _message_for(verdict.reason_code),
    )


DEFAULT_REASON_MESSAGE = "생성 결과가 품질·안전성 기준을 통과하지 못했습니다."


def _message_for(reason_code: str | None) -> str:
    return SAFETY_REASON_MESSAGES.get(reason_code or "", DEFAULT_REASON_MESSAGE)


# 거부 사유 코드 -> 사용자에게 보일 한국어 문구.
#
# 공개 상수인 이유: 백엔드/프론트가 `safety.reasonCode`를 받아 화면 문구를 고르려면
# 어떤 코드가 나올 수 있는지 알아야 한다. 양쪽에 문자열을 다시 하드코딩하는 대신
# `GET /v1/meta`의 `safetyReasonCodes`로 이 표를 그대로 내보낸다.
SAFETY_REASON_MESSAGES: dict[str, str] = {
    "HARMFUL_CONTENT": "생성 결과에 부적절한 내용이 포함되어 제공할 수 없습니다.",
    "FACE_DISTORTED": "인물의 얼굴이 부자연스럽게 생성되어 제공할 수 없습니다.",
    "FACE_NOT_PRESERVED": "결과의 얼굴이 업로드한 사진의 인물과 달라 제공할 수 없습니다.",
    "PROPORTION_ERROR": "인물의 신체 비율이 사람의 것이 아니어서 제공할 수 없습니다.",
    "SCENE_SCALE_BROKEN": "인물과 배경의 크기·원근이 맞지 않아 제공할 수 없습니다.",
    "ANATOMY_ERROR": "인물의 신체가 부자연스럽게 생성되어 제공할 수 없습니다.",
    "PERSON_COUNT_MISMATCH": "결과에 인물이 올바르게 생성되지 않았습니다.",
    "SEVERE_ARTIFACTS": "생성 결과의 품질이 기준에 미치지 못했습니다.",
    "BACKGROUND_ALTERED": "배경 관광지 사진이 원본과 다르게 변형되어 제공할 수 없습니다.",
    "PROVIDER_BLOCKED": "AI 공급자의 안전성 정책에 따라 생성이 거부되었습니다.",
}
