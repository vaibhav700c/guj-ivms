"""ANPR analytics worker — edge/regional node (optional full-stack service).

In the complete deployment (docker-compose profile `analytics`), this worker:
  1. pulls RTSP frames from camera sources (OpenCV / GStreamer),
  2. runs YOLOv8 vehicle/person detection + ByteTrack tracking,
  3. crops plates and OCRs with PaddleOCR (Indian plate preprocessing),
  4. pushes structured metadata to the central platform ingest API.

This repo ships the worker skeleton without heavy ML dependencies so the
cloud build stays light; install `analytics/requirements.txt` to run it
against real camera streams (plan §5, §20 Week 2).

Usage:
    INGEST_URL=http://backend:8000 INGEST_API_KEY=... python worker.py
"""
import os
import time

import httpx

INGEST_URL = os.environ.get("INGEST_URL", "http://localhost:8000")
INGEST_API_KEY = os.environ.get("INGEST_API_KEY", "")
CAMERA_SOURCES = {
    # camera_id: rtsp_url  (populated from the camera registry in production)
}

SAMPLE_EVENT = {
    "camera_id": 1,
    "plate_text": "GJ 01 AB 1234",
    "confidence": 0.94,
    "ocr_confidence": 0.91,
    "vehicle_type": "car",
    "direction": "inbound",
}


def push_event(client: httpx.Client, event: dict) -> None:
    r = client.post(
        f"{INGEST_URL}/api/v1/ingest/anpr",
        json=event,
        headers={"X-API-Key": INGEST_API_KEY},
    )
    r.raise_for_status()
    print("ingested:", r.json())


def main() -> None:
    """Frame loop placeholder — replace `detect_and_ocr` with the real pipeline.

    Real pipeline (see plan.md §5):
        results = yolo(frame)                      # vehicle detection
        tracks  = byte_track.update(results)       # within-camera tracking
        plates  = plate_detector(crop, track)      # plate localization
        text    = paddle_ocr(enhance(plates))      # Indian plate OCR
    """
    with httpx.Client(timeout=10) as client:
        while True:
            try:
                push_event(client, SAMPLE_EVENT)
            except Exception as exc:
                print("ingest failed:", exc)
            time.sleep(5)


if __name__ == "__main__":
    main()
