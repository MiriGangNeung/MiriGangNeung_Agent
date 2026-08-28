"""사진 유효성 검사 (요구사항 B3, B4).

검사 순서는 싼 것부터: 용량 -> 실제 파일 시그니처 -> 픽셀 수 -> 얼굴 검출 -> 선명도 -> 가림.

얼굴 검출기:
- 기본은 OpenCV에 번들된 Haar cascade라 추가 다운로드 없이 동작한다.
- `FACE_MODEL_PATH`에 YuNet ONNX(face_detection_yunet_2023mar.onnx)를 놓으면 그쪽을 쓴다.
  YuNet이 정확도가 높으므로 운영 환경에서는 모델 파일을 주입하는 편이 좋다. 리포에
  `models/face_detection_yunet_2023mar.onnx`를 커밋해 뒀고, `.env.example`의 기본값도
  그쪽을 가리킨다.
"""

from __future__ import annotations

import io
import logging
import os
from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image, UnidentifiedImageError

from app.core.config import get_settings
from app.core.errors import AiServiceError

logger = logging.getLogger(__name__)

ALLOWED_FORMATS = frozenset({"JPEG", "PNG", "WEBP"})
ALLOWED_MIME = frozenset({"image/jpeg", "image/png", "image/webp"})

# 얼굴 ROI Laplacian 분산이 이 값보다 낮으면 초점이 맞지 않은 것으로 본다.
BLUR_VARIANCE_THRESHOLD = 45.0
# 얼굴이 전체 이미지에서 차지하는 최소 비율. 너무 작으면 합성에 쓸 디테일이 없다.
MIN_FACE_AREA_RATIO = 0.004
# 눈 검출 ROI를 최소 이 높이까지 확대한 뒤 판정한다 (`_is_face_occluded` 참고).
EYE_ROI_MIN_HEIGHT = 120


@dataclass
class FaceBox:
    x: int
    y: int
    w: int
    h: int

    @property
    def area(self) -> int:
        return self.w * self.h


@dataclass
class ValidationReport:
    format: str
    width: int
    height: int
    face: FaceBox
    sharpness: float


def validate_photo(
    data: bytes, declared_mime: str | None, *, max_bytes: int, max_pixels: int
) -> ValidationReport:
    if len(data) > max_bytes:
        raise AiServiceError("IMAGE_TOO_LARGE")

    if declared_mime and declared_mime.lower() not in ALLOWED_MIME:
        # 선언 MIME은 신뢰하지 않지만, 명백히 다른 값이면 여기서 빨리 끊는다.
        raise AiServiceError("INVALID_IMAGE_FORMAT")

    image_format, size = _probe_real_format(data)
    width, height = size

    if width * height > max_pixels:
        # 압축 폭탄 차단 (검토 총평 §4)
        raise AiServiceError("IMAGE_TOO_MANY_PIXELS")

    matrix = _to_bgr_matrix(data)
    faces = detect_faces(matrix)

    if not faces:
        raise AiServiceError("NO_PERSON_DETECTED")
    if len(faces) > 1:
        # P0에서는 한 명이 촬영된 사진만 허용한다 (요구사항 B3).
        raise AiServiceError("MULTIPLE_PERSONS")

    face = faces[0]
    if face.area / float(width * height) < MIN_FACE_AREA_RATIO:
        raise AiServiceError("NO_PERSON_DETECTED", "인물이 너무 작게 찍혀 있습니다.")

    sharpness = _face_sharpness(matrix, face)
    if sharpness < BLUR_VARIANCE_THRESHOLD:
        raise AiServiceError("IMAGE_TOO_BLURRY")

    if _is_face_occluded(matrix, face):
        raise AiServiceError("FACE_OCCLUDED")

    return ValidationReport(
        format=image_format, width=width, height=height, face=face, sharpness=sharpness
    )


def _probe_real_format(data: bytes) -> tuple[str, tuple[int, int]]:
    """확장자·MIME을 믿지 않고 실제 디코딩으로 형식을 확인한다."""
    try:
        with Image.open(io.BytesIO(data)) as probe:
            probe.verify()  # 손상 여부 확인 (verify 후에는 재사용 불가)
        with Image.open(io.BytesIO(data)) as image:
            image_format = (image.format or "").upper()
            size = image.size
            n_frames = getattr(image, "n_frames", 1)
            animated = getattr(image, "is_animated", False) or n_frames > 1
    except (UnidentifiedImageError, OSError, ValueError):
        raise AiServiceError(
            "INVALID_IMAGE_FORMAT", "이미지를 읽을 수 없거나 손상되었습니다."
        ) from None

    if image_format not in ALLOWED_FORMATS:
        raise AiServiceError("INVALID_IMAGE_FORMAT")
    if animated:
        raise AiServiceError("INVALID_IMAGE_FORMAT", "애니메이션 이미지는 사용할 수 없습니다.")
    return image_format, size


def _to_bgr_matrix(data: bytes) -> np.ndarray:
    matrix = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    if matrix is None:
        raise AiServiceError("INVALID_IMAGE_FORMAT", "이미지를 디코딩할 수 없습니다.")
    return matrix


def detect_faces(matrix: np.ndarray) -> list[FaceBox]:
    model_path = get_settings().resolved_face_model_path
    if model_path and os.path.isfile(model_path):
        try:
            return _detect_with_yunet(matrix, model_path)
        except Exception:  # noqa: BLE001 - 모델 로드 실패 시 번들 검출기로 폴백
            logger.warning("YuNet 검출에 실패해 Haar cascade로 폴백합니다.")
    return _detect_with_haar(matrix)


def _detect_with_yunet(matrix: np.ndarray, model_path: str) -> list[FaceBox]:
    height, width = matrix.shape[:2]
    detector = cv2.FaceDetectorYN.create(model_path, "", (width, height), 0.7, 0.3, 5000)
    _, faces = detector.detect(matrix)
    if faces is None:
        return []
    return [FaceBox(int(f[0]), int(f[1]), int(f[2]), int(f[3])) for f in faces]


def _detect_with_haar(matrix: np.ndarray) -> list[FaceBox]:
    gray = cv2.cvtColor(matrix, cv2.COLOR_BGR2GRAY)
    gray = cv2.equalizeHist(gray)
    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    detections = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=6, minSize=(48, 48))
    return [FaceBox(int(x), int(y), int(w), int(h)) for (x, y, w, h) in detections]


def _face_sharpness(matrix: np.ndarray, face: FaceBox) -> float:
    roi = matrix[face.y : face.y + face.h, face.x : face.x + face.w]
    if roi.size == 0:
        return 0.0
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def _is_face_occluded(matrix: np.ndarray, face: FaceBox) -> bool:
    """얼굴 상단 절반에서 눈이 하나도 검출되지 않으면 가려진 것으로 본다.

    Haar 눈 캐스케이드는 눈이 대략 20px 이상일 때부터 안정적으로 검출된다. 전신샷
    처럼 얼굴이 작게 찍힌 사진은 이 ROI가 수십 px에 불과해, 얼굴이 멀쩡히 보여도
    눈을 하나도 못 찾아 전부 '가려짐'으로 오판했다. 그래서 검출 전에 ROI를 최소
    높이까지 확대한다 — 원본이 이미 충분히 크면 그대로 쓴다.
    """
    roi = matrix[face.y : face.y + face.h // 2, face.x : face.x + face.w]
    if roi.size == 0:
        return True
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    if gray.shape[0] < EYE_ROI_MIN_HEIGHT:
        scale = EYE_ROI_MIN_HEIGHT / gray.shape[0]
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_eye.xml")
    eyes = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4)
    return len(eyes) == 0
