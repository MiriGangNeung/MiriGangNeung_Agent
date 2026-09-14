FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# opencv-python-headless가 요구하는 최소 런타임 라이브러리
RUN apt-get update \
    && apt-get install -y --no-install-recommends libglib2.0-0 curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY prompts ./prompts
COPY assets ./assets
COPY models ./models
COPY main.py .

# 얼굴 인식 모델(SFace, 38MB)은 용량 때문에 git에서 빠져 있다. 로컬에서는 받아둔
# 파일이 복사되지만, CI처럼 새로 clone한 곳에서 빌드하면 파일 없이 이미지가 만들어지고
# 서비스는 에러 없이 얼굴 유사도 판정·재생성만 조용히 꺼진 채 뜬다. 그래서 빌드
# 단계에서 없으면 받고, 받은 파일이든 복사된 파일이든 체크섬으로 확인한다.
COPY scripts/download_models.sh ./scripts/download_models.sh
RUN bash scripts/download_models.sh \
    && echo "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79  models/face_recognition_sface_2021dec.onnx" \
       | sha256sum -c -

ENV PORT=8100
EXPOSE 8100

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://localhost:8100/health || exit 1

CMD ["python", "main.py"]
