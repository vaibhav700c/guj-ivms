FROM python:3.12-slim

WORKDIR /app

# opencv runtime libs (libGL not needed with headless wheels, but ffmpeg for
# robust RTSP decode is bundled inside opencv-python-headless wheels)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    OPENCV_FFMPEG_CAPTURE_OPTIONS=rtsp_transport;tcp

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY worker.py .

# cameras processed by this edge node (override at deploy time)
ENV CAMERA_IDS=1,6,12 \
    SAMPLE_FPS=1.0

CMD ["python", "worker.py", "run"]