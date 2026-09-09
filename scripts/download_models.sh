#!/usr/bin/env bash
# 얼굴 인식 모델(SFace)을 받는다. 얼굴 검출 모델(YuNet)은 작아서 리포에 커밋돼 있다.
#
# 없어도 서비스는 정상 동작한다 — 얼굴 신원 유사도 판정과 그에 따른 재생성만
# 생략되고, 합성은 1회로 끝난다.
set -euo pipefail
cd "$(dirname "$0")/.."

DEST="models/face_recognition_sface_2021dec.onnx"
URL="https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx"

if [ -f "$DEST" ]; then
  echo "이미 있음: $DEST"
  exit 0
fi

mkdir -p models
echo "받는 중: $DEST (약 38MB, opencv_zoo, Apache-2.0)"
curl -fsSL -o "$DEST" "$URL"
echo "완료."
