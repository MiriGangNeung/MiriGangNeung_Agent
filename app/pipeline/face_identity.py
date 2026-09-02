"""얼굴 동일인 판정 — 로컬 임베딩 코사인 유사도.

왜 로컬인가: 합성 결과가 업로드한 본인인지 판정하는 일을 Gemini에 물으면 호출 1회당
5~12초가 든다. 재생성 루프처럼 시도마다 부르는 자리에서는 작업 시간이 N배가 되어
실서비스에 쓸 수 없다. SFace(ONNX)는 CPU에서 0.2초 안팎이고 비용이 0이며, 무엇보다
**수치**를 돌려주기 때문에 임계값을 데이터로 정할 수 있다.

`quality_check_v3.md`의 `face_matches_subject`(Gemini 판정)는 그대로 두되 관측용이다.
최종 품질 검사는 어차피 vision 호출 1회라 필드가 늘어도 비용이 같고, 두 판정을 나란히
기록해 두면 임계값을 보정할 때 서로를 검증할 수 있다.

모델이 없거나 얼굴을 못 찾으면 예외를 던지지 않고 `None`을 돌려준다 — 신원 판정은
품질을 올리는 보조 수단이지 합성의 전제 조건이 아니다. `validate.py`가 YuNet 실패 시
Haar로 폴백하는 것과 같은 원칙이다.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache

import cv2
import numpy as np

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# SFace 문서가 제시하는 동일인 판정 기준(코사인). 서비스 임계값은 설정으로 따로 두고
# 이 값보다 낮게(=널널하게) 잡는다 — 얼굴이 조금 달라도 결과는 내주는 것이 정책이다.
SFACE_REFERENCE_COSINE = 0.363

# YuNet 검출 신뢰도. validate.py와 같은 값을 쓴다.
_DETECT_SCORE_THRESHOLD = 0.7
_DETECT_NMS_THRESHOLD = 0.3
_DETECT_TOP_K = 5000


@lru_cache
def _recognizer() -> cv2.FaceRecognizerSF | None:
    path = get_settings().resolved_face_recognition_model_path
    if not path or not os.path.isfile(path):
        logger.info("얼굴 인식 모델이 없어 신원 유사도 판정을 건너뜁니다.")
        return None
    try:
        return cv2.FaceRecognizerSF.create(path, "")
    except Exception:  # noqa: BLE001 - 모델 로드 실패는 판정 생략으로 흡수한다
        logger.warning("얼굴 인식 모델을 로드하지 못했습니다.", exc_info=True)
        return None


def _detect_rows(matrix: np.ndarray) -> np.ndarray | None:
    """YuNet 원본 검출 행(상자 4 + 랜드마크 10 + 점수 1)을 그대로 돌려준다.

    `validate.py::detect_faces`는 `FaceBox`만 돌려주느라 랜드마크를 버린다. SFace의
    `alignCrop`은 그 랜드마크로 얼굴을 정렬하고, 정렬 없이 넣으면 임베딩 품질이
    크게 떨어진다. 검증 게이트를 건드리지 않으려고 여기서 따로 검출한다.
    """
    model_path = get_settings().resolved_face_model_path
    if not model_path or not os.path.isfile(model_path):
        # Haar에는 랜드마크가 없어 정렬을 할 수 없다. 판정을 생략한다.
        return None

    height, width = matrix.shape[:2]
    try:
        detector = cv2.FaceDetectorYN.create(
            model_path,
            "",
            (width, height),
            _DETECT_SCORE_THRESHOLD,
            _DETECT_NMS_THRESHOLD,
            _DETECT_TOP_K,
        )
        _, faces = detector.detect(matrix)
    except Exception:  # noqa: BLE001
        logger.warning("신원 판정용 얼굴 검출에 실패했습니다.", exc_info=True)
        return None

    if faces is None or len(faces) == 0:
        return None
    # 여러 명이면 가장 큰 얼굴 = 주 피사체. 배경에 찍힌 행인을 잡으면 안 된다.
    return faces[np.argmax(faces[:, 2] * faces[:, 3])]


def _embed(image: bytes) -> np.ndarray | None:
    recognizer = _recognizer()
    if recognizer is None:
        return None

    matrix = cv2.imdecode(np.frombuffer(image, np.uint8), cv2.IMREAD_COLOR)
    if matrix is None:
        return None

    row = _detect_rows(matrix)
    if row is None:
        return None

    try:
        aligned = recognizer.alignCrop(matrix, row)
        return recognizer.feature(aligned)
    except Exception:  # noqa: BLE001
        logger.warning("얼굴 임베딩 추출에 실패했습니다.", exc_info=True)
        return None


def face_similarity(reference: bytes, candidate: bytes) -> float | None:
    """두 이미지 속 주 얼굴의 코사인 유사도. 판정할 수 없으면 None.

    1.0에 가까울수록 같은 사람이다. `None`은 "다른 사람"이 아니라 "모르겠다"는 뜻이라,
    호출부는 이 값을 실패로 취급하면 안 된다.
    """
    left = _embed(reference)
    if left is None:
        return None
    right = _embed(candidate)
    if right is None:
        return None

    recognizer = _recognizer()
    if recognizer is None:  # pragma: no cover - _embed에서 이미 걸러진다
        return None
    return float(recognizer.match(left, right, cv2.FaceRecognizerSF_FR_COSINE))


def face_ratio(image: bytes) -> float | None:
    """주 얼굴 높이가 이미지 높이에서 차지하는 비율. 얼굴이 없으면 None.

    절대 픽셀이 아니라 비율을 쓴다 — 모델이 얼굴에 배정하는 표현 용량은 프레임 대비
    크기를 따라가지, 원본 파일이 몇 픽셀인지를 따라가지 않는다. 고해상도 전신샷은
    절대 크기가 커도 얼굴 비중은 낮다.
    """
    matrix = cv2.imdecode(np.frombuffer(image, np.uint8), cv2.IMREAD_COLOR)
    if matrix is None:
        return None

    height = matrix.shape[0]
    if height == 0:
        return None

    # 여기서는 랜드마크가 필요 없으므로 검증 단계와 같은 검출기를 그대로 쓴다
    # (YuNet이 없으면 Haar로 폴백해 최소한 상자는 얻는다).
    from app.pipeline.validate import detect_faces

    faces = detect_faces(matrix)
    if not faces:
        return None
    return max(f.h for f in faces) / height


__all__ = ["face_similarity", "face_ratio", "SFACE_REFERENCE_COSINE"]
