"""합성 모델에 함께 넘길 얼굴 참조 이미지를 만든다.

왜 필요한가: 업로드 사진에서 얼굴이 차지하는 픽셀이 작으면(`woman1.jpg`는 66×96)
합성 모델이 얼굴을 **복사하지 않고 재구성한다**. 결과는 자연스럽지만 다른 사람이고,
품질 검사의 `face_matches_subject`가 이를 거부한다. 프롬프트로 "얼굴을 그대로
유지하라"고 아무리 강하게 지시해도 참조할 픽셀 자체가 없으면 소용이 없다.

그래서 원본 사진과 별개로, 검출된 얼굴 영역만 잘라 확대한 이미지를 한 장 더
넘긴다. 확대가 정보를 새로 만들어내지는 않지만, 모델이 얼굴에 배정하는 표현
용량이 늘어나 이목구비가 뭉개지지 않는다는 것이 이 접근의 가정이다 —
`scripts/face_experiment.py`가 이 가정을 실제로 측정한다.
"""

from __future__ import annotations

import io
import logging

import cv2
import numpy as np
from PIL import Image

from app.pipeline.validate import FaceBox, detect_faces

logger = logging.getLogger(__name__)

# 얼굴 상자 주변으로 얼마나 더 잡을지. 머리카락 경계·턱선·귀가 정체성에 크게
# 기여하는데 검출 상자는 대개 그것들을 잘라낸다.
FACE_CROP_MARGIN = 0.6

# 잘라낸 얼굴을 최소 이 크기까지 확대한다. 이보다 크면 그대로 둔다.
MIN_FACE_EDGE = 512


def build_face_reference(
    image: bytes, margin: float = FACE_CROP_MARGIN, min_edge: int = MIN_FACE_EDGE
) -> tuple[bytes, str] | None:
    """업로드 사진에서 얼굴만 잘라 확대한 PNG. 얼굴을 못 찾으면 None.

    검출에 실패해도 예외를 던지지 않는다 — 얼굴 참조는 품질을 높이는 보조 입력이지
    합성의 전제 조건이 아니다. 없으면 기존과 동일하게 동작해야 한다.
    """
    try:
        matrix = cv2.imdecode(np.frombuffer(image, np.uint8), cv2.IMREAD_COLOR)
        if matrix is None:
            return None
        faces = detect_faces(matrix)
    except Exception:  # noqa: BLE001 - 참조 이미지 실패가 합성을 막으면 안 된다
        logger.warning("얼굴 참조 이미지를 만들지 못했습니다.", exc_info=True)
        return None

    if not faces:
        return None

    # 여러 명이면 가장 큰 얼굴. 앞선 검증 단계에서 이미 주 피사체만 남기지만,
    # 이 함수만 따로 호출하는 경로(실험 스크립트)를 위해 여기서도 고른다.
    face = max(faces, key=lambda f: f.area)
    crop = _crop_with_margin(matrix, face, margin)
    if crop is None:
        return None

    return _encode_upscaled(crop, min_edge), "image/png"


def _crop_with_margin(matrix: np.ndarray, face: FaceBox, margin: float) -> np.ndarray | None:
    height, width = matrix.shape[:2]
    pad_x = int(face.w * margin)
    pad_y = int(face.h * margin)

    left = max(0, face.x - pad_x)
    top = max(0, face.y - pad_y)
    right = min(width, face.x + face.w + pad_x)
    bottom = min(height, face.y + face.h + pad_y)
    if right <= left or bottom <= top:
        return None
    return matrix[top:bottom, left:right]


def _encode_upscaled(crop: np.ndarray, min_edge: int) -> bytes:
    image = Image.fromarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB))
    scale = min_edge / min(image.width, image.height)
    if scale > 1.0:
        image = image.resize(
            (max(1, round(image.width * scale)), max(1, round(image.height * scale))),
            Image.LANCZOS,
        )

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


__all__ = ["build_face_reference", "FACE_CROP_MARGIN", "MIN_FACE_EDGE"]
