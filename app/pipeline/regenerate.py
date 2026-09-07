"""얼굴 신원이 살아날 때까지 합성을 다시 시도한다.

생성은 확률적이라 같은 입력도 매번 다른 얼굴이 나온다. 그래서 한 번 뽑고 마는 대신
여러 번 뽑아 가장 닮은 것을 고른다 — 통과율이 `1-(1-p)^N`으로 오른다.

**판정은 로컬에서 한다** (`app/pipeline/face_identity.py`). 시도마다 Gemini에 물으면
호출 1회당 5~12초라 작업 시간이 N배가 되어 실서비스에 쓸 수 없다. SFace 임베딩
비교는 0.2초에 비용이 0이다. 따라서 이 루프가 늘리는 것은 **이미지 생성 호출뿐이고
vision 호출 수는 그대로다.**

실패해도 예외를 던지지 않는다. 상한까지 갔으면 그중 가장 점수가 높은 결과를 돌려주고,
경고를 달지 말지는 호출부가 정한다 — 사용자에게 결과는 반드시 준다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.pipeline.compose import compose_with_retry
from app.pipeline.face_identity import face_similarity
from app.providers.base import CompositionOutput, CompositionRequest, ImageCompositionProvider

logger = logging.getLogger(__name__)


@dataclass
class RegenerationResult:
    output: CompositionOutput
    # 채택한 결과의 얼굴 유사도. 얼굴을 못 찾았거나 인식 모델이 없으면 None
    # ("다른 사람"이 아니라 "판정 불가"라는 뜻이다).
    similarity: float | None
    # 실제로 부른 이미지 생성 횟수 (compose_with_retry 내부의 오류 재시도까지 합산).
    compose_calls: int
    # 얼굴 때문에 다시 뽑은 횟수. 관측용.
    face_attempts: int


async def compose_until_face_matches(
    provider: ImageCompositionProvider,
    request: CompositionRequest,
    *,
    reference_image: bytes,
    timeout_seconds: float,
    max_retries: int,
    max_attempts: int,
    similarity_target: float,
    on_attempt=None,
) -> RegenerationResult:
    """얼굴 유사도가 `similarity_target` 이상이 될 때까지 최대 `max_attempts`번 합성한다.

    `on_attempt`이 주어지면 시도 사이에 호출한다. 취소 확인처럼 루프 중간에 끼워야
    하는 일을 호출부가 넣을 수 있게 하기 위한 것이다 (예외를 던지면 루프가 멈춘다).
    """
    best: CompositionOutput | None = None
    best_score: float | None = None
    compose_calls = 0

    for attempt in range(1, max(1, max_attempts) + 1):
        if on_attempt is not None and attempt > 1:
            on_attempt()

        output, calls = await compose_with_retry(
            provider, request, timeout_seconds=timeout_seconds, max_retries=max_retries
        )
        compose_calls += calls

        score = face_similarity(reference_image, output.image)
        if score is None:
            # 판정할 수 없으면 더 뽑아도 고를 기준이 없다. 첫 결과를 그대로 쓴다.
            logger.info("얼굴 유사도를 판정할 수 없어 재생성 없이 진행합니다.")
            return RegenerationResult(output, None, compose_calls, attempt)

        if best_score is None or score > best_score:
            best, best_score = output, score

        if score >= similarity_target:
            logger.info("얼굴 유사도 %.3f (시도 %d) — 목표 달성.", score, attempt)
            return RegenerationResult(output, score, compose_calls, attempt)

        logger.info(
            "얼굴 유사도 %.3f < 목표 %.3f (시도 %d/%d) — 다시 뽑습니다.",
            score, similarity_target, attempt, max_attempts,
        )

    # 상한 소진. 버리지 않고 가장 닮은 후보를 쓴다.
    assert best is not None  # 루프가 최소 1회 돌므로 항상 채워진다
    logger.info("재생성 상한 소진 — 최고 유사도 %.3f 결과를 채택합니다.", best_score)
    return RegenerationResult(best, best_score, compose_calls, max(1, max_attempts))


__all__ = ["compose_until_face_matches", "RegenerationResult"]
