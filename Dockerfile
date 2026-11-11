FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg curl espeak-ng && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
RUN mkdir -p models && \
    curl -fL --retry 3 -o models/ar_JO-kareem-medium.onnx https://huggingface.co/rhasspy/piper-voices/resolve/main/ar/ar_JO/kareem/medium/ar_JO-kareem-medium.onnx && \
    curl -fL --retry 3 -o models/ar_JO-kareem-medium.onnx.json https://huggingface.co/rhasspy/piper-voices/resolve/main/ar/ar_JO/kareem/medium/ar_JO-kareem-medium.onnx.json && \
    echo "9e95cab07b679da603bba17c4dec7ab3111320571964ee95c0379603c086491e  models/ar_JO-kareem-medium.onnx" | sha256sum -c -
COPY backend/app.py ./app.py
ENV PYTHONUNBUFFERED=1
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-10000} --workers 1"]
