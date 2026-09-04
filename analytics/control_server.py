"""Local inference control server — the operator-facing bridge for the
"Investigate" feature (wanted-person photo search + live plate watch).

This runs ONLY on the local machine, never on Render (see CLAUDE.md: the ML
stack needs ~2GB RAM and Render's free tier has 512MB). It reuses every piece
of the existing edge pipeline in `worker.py` (YOLOv8, ByteTrack, plate OCR,
InsightFace ArcFace gallery, the ingest client) instead of duplicating any of
it — this file only adds camera-selection + job orchestration + an HTTP
surface the Vercel-hosted (or local dev) frontend can call directly from the
operator's browser.

    Frontend (browser, same machine as this process)
        │  POST /api/local/watchlist/enroll-photo  (multipart image)
        │  POST /api/local/monitor/start            {mode, entry_id|plate, camera_ids}
        ▼
    control_server.py ──▶ worker.CameraPipeline(s) ──▶ RTSP (Sentinel grid)
        │                                                   │
        │                                          YOLOv8 / plate OCR / ArcFace
        │                                                   ▼
        └──────────────────────────────▶ POST /api/v1/ingest/{anpr,detection}
                                          (existing Render backend — unchanged)
                                                   │
                                    existing watchlist correlation → Alert
                                    (already tested: backend/tests/test_api.py)

Run (from analytics/, same venv as worker.py — needs insightface installed
for the face-search half of this to actually match anything):

    .venv/bin/pip install -r requirements.txt
    .venv/bin/uvicorn control_server:app --port 8800

Then point the frontend's "Investigate" page at http://localhost:8800.
"""
from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from typing import Literal

import cv2
import httpx
import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import worker  # noqa: E402 — reuse the real pipeline, models, ingest client

log = logging.getLogger("control-server")

HERE = os.path.dirname(os.path.abspath(__file__))
FRAMES_DIR = os.path.join(HERE, "local_frames")
REF_DIR = os.path.join(FRAMES_DIR, "refs")
DETECTIONS_DIR = os.path.join(FRAMES_DIR, "detections")
PORT = int(os.environ.get("CONTROL_SERVER_PORT", "8800"))

os.makedirs(REF_DIR, exist_ok=True)
os.makedirs(DETECTIONS_DIR, exist_ok=True)

# Opt the shared worker module into snapshot-on-match — off by default for
# plain `worker.py run`, on here because a demo is pointless without frames.
worker.LOCAL_SNAPSHOT_DIR = DETECTIONS_DIR
worker.LOCAL_SNAPSHOT_BASE_URL = os.environ.get(
    "LOCAL_SNAPSHOT_BASE_URL", f"http://localhost:{PORT}/local-frames/detections"
)

MAX_CAMERAS_PER_JOB = int(os.environ.get("MAX_CAMERAS_PER_JOB", "6"))
MAX_TOTAL_CAMERAS = int(os.environ.get("MAX_TOTAL_CAMERAS", "8"))
JOB_TTL_S = float(os.environ.get("JOB_TTL_S", str(20 * 60)))  # auto-stop a forgotten job

app = FastAPI(title="Gujarat IVMS — Local Inference Control")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://guj-ivms.vercel.app",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/local-frames", StaticFiles(directory=FRAMES_DIR), name="local-frames")

# ── Shared pipeline state — one CameraPipeline per camera id, reference-
# counted across jobs so two jobs watching the same camera share one RTSP
# connection instead of opening it twice. ────────────────────────────────────
_lock = threading.Lock()
_ingest = worker.Ingest()
_gallery = worker.FaceGallery(_ingest)
_yolo_lock = threading.Lock()
_pipelines: dict[int, worker.CameraPipeline] = {}
_refcount: dict[int, int] = {}
_jobs: dict[str, dict] = {}
# camera_id -> local file path / webcam index, for cameras registered via
# /api/local/cameras/register-local instead of the Sentinel grid.
_video_sources: dict[int, str | int] = {}


def _start_camera_locked(camera_id: int) -> None:
    if camera_id in _pipelines:
        return
    p = worker.CameraPipeline(
        camera_id, _ingest, _yolo_lock, _gallery,
        video_source=_video_sources.get(camera_id),
    )
    p.start()
    _pipelines[camera_id] = p


def _release_camera_locked(camera_id: int) -> None:
    _refcount[camera_id] = _refcount.get(camera_id, 1) - 1
    if _refcount[camera_id] <= 0:
        p = _pipelines.pop(camera_id, None)
        _refcount.pop(camera_id, None)
        if p is not None:
            p.stop()


def _stop_job(job_id: str) -> dict | None:
    with _lock:
        job = _jobs.get(job_id)
        if job is None or job["status"] != "running":
            return job
        for cid in job["camera_ids"]:
            _release_camera_locked(cid)
        job["status"] = "stopped"
        job["stopped_at"] = time.time()
        return job


def _backend_get(path: str) -> dict:
    r = httpx.get(f"{worker.INGEST_URL}/api/v1{path}", timeout=15)
    r.raise_for_status()
    return r.json()


def _backend_post(path: str, payload: dict) -> dict:
    headers = {"X-API-Key": worker.INGEST_API_KEY} if worker.INGEST_API_KEY else {}
    r = httpx.post(f"{worker.INGEST_URL}/api/v1{path}", json=payload, headers=headers, timeout=15)
    r.raise_for_status()
    return r.json()


@app.get("/api/local/health")
def health():
    with _lock:
        running_jobs = sum(1 for j in _jobs.values() if j["status"] == "running")
        cameras_active = list(_pipelines.keys())
    return {
        "status": "ok",
        "backend_url": worker.INGEST_URL,
        "models": {
            "yolo": bool(worker.MODELS.yolo),
            "anpr": bool(worker.MODELS.plate_det and worker.MODELS.plate_ocr),
            "face": bool(worker.MODELS.face_app),
        },
        "jobs_running": running_jobs,
        "cameras_active": cameras_active,
    }


@app.post("/api/local/watchlist/enroll-photo")
async def enroll_photo(
    file: UploadFile = File(...),
    identifier: str = Form(...),
    severity: str = Form("critical"),
    entry_id: int | None = Form(None),
):
    if not worker.MODELS.face_app:
        raise HTTPException(
            503,
            "Face recognition is not loaded on this local machine "
            "(pip install insightface onnxruntime, then restart control_server.py).",
        )
    raw = await file.read()
    arr = np.frombuffer(raw, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(422, "Could not decode the uploaded file as an image.")

    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    faces = worker.MODELS.face_app.get(rgb)
    if not faces and max(img.shape[:2]) < 480:
        # The live pipeline's det_size (worker.py, now 1280x1280) still
        # expects roughly CCTV-frame-sized input; a small reference photo
        # (e.g. a cropped ID photo) benefits from being upscaled toward that
        # scale first rather than run through the detector tiny.
        scale = 480 / max(img.shape[:2])
        upscaled = cv2.resize(rgb, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        faces = worker.MODELS.face_app.get(upscaled)
    if not faces:
        raise HTTPException(422, "No face detected in the uploaded photo — use a clear, front-facing image.")
    # Largest face by box area, in case the photo has bystanders in frame.
    faces.sort(key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]), reverse=True)
    face = faces[0]
    embedding = [round(float(v), 5) for v in face.normed_embedding.tolist()]
    det_conf = float(getattr(face, "det_score", 1.0))

    try:
        if entry_id is None:
            created = _backend_post("/watchlist", {
                "category": "wanted_person",
                "subject_type": "person",
                "identifier": identifier,
                "severity": severity,
                "description": "Added via Investigate — local photo upload",
            })
            entry_id = created["id"]
        enrolled = _backend_post(f"/watchlist/{entry_id}/enroll-face", {"embedding": embedding})
    except httpx.HTTPStatusError as exc:
        raise HTTPException(exc.response.status_code, f"Backend rejected enrollment: {exc.response.text}") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"Could not reach backend at {worker.INGEST_URL}: {exc}") from exc

    cv2.imwrite(os.path.join(REF_DIR, f"{entry_id}.jpg"), img)
    with _lock:
        _gallery.refresh(force=True)  # so a job already running picks this up immediately

    return {
        "entry_id": entry_id,
        "identifier": identifier,
        "status": "enrolled",
        "embedding_dim": enrolled.get("embedding_dim", len(embedding)),
        "face_detect_confidence": round(det_conf, 3),
        "reference_photo_url": f"http://localhost:{PORT}/local-frames/refs/{entry_id}.jpg",
        "faces_in_photo": len(faces),
    }


class RegisterLocalCamera(BaseModel):
    name: str
    video_path: str  # local file path, or a webcam index as a string e.g. "0"
    latitude: float = 23.2156   # Gandhinagar HQ — placeholder for a demo-only camera
    longitude: float = 72.6369


@app.post("/api/local/cameras/register-local")
def register_local_camera(body: RegisterLocalCamera):
    """Register a local video file / webcam as a real camera row, so the
    existing camera-management, GIS and Live View pages all see it exactly
    like a Sentinel-grid camera. Lets the Investigate demo run against local
    footage when the live grid has no usable footage for a given target
    (e.g. no close-up faces on the traffic-angle Sentinel cameras)."""
    source: str | int = body.video_path
    if body.video_path.strip().isdigit():
        source = int(body.video_path.strip())  # webcam device index
    elif not os.path.exists(body.video_path):
        raise HTTPException(422, f"video_path does not exist on this machine: {body.video_path}")

    try:
        created = _backend_post("/cameras", {
            "name": body.name,
            "latitude": body.latitude,
            "longitude": body.longitude,
            "city": "Local Demo",
            "camera_type": "local_video" if isinstance(source, str) else "webcam",
            "analytics_tier": "A",
        })
    except httpx.HTTPStatusError as exc:
        raise HTTPException(exc.response.status_code, exc.response.text) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"Could not reach backend at {worker.INGEST_URL}: {exc}") from exc

    camera_id = created["id"]
    with _lock:
        _video_sources[camera_id] = source
    return {"camera_id": camera_id, "name": body.name, "source": str(source)}


class MonitorStart(BaseModel):
    mode: Literal["face", "plate"]
    entry_id: int | None = None
    plate: str | None = None
    camera_ids: list[int]


@app.post("/api/local/monitor/start")
def monitor_start(body: MonitorStart):
    if not body.camera_ids:
        raise HTTPException(422, "camera_ids must not be empty")
    if len(body.camera_ids) > MAX_CAMERAS_PER_JOB:
        raise HTTPException(422, f"At most {MAX_CAMERAS_PER_JOB} cameras per job on this machine's CPU budget")

    with _lock:
        already = set(_pipelines.keys())
        projected = already | set(body.camera_ids)
        if len(projected) > MAX_TOTAL_CAMERAS:
            raise HTTPException(
                422,
                f"Would exceed the local machine's cap of {MAX_TOTAL_CAMERAS} concurrently "
                f"monitored cameras ({len(already)} already running). Stop another job first.",
            )

    if body.mode == "face":
        if not body.entry_id:
            raise HTTPException(422, "entry_id is required for mode=face")
        target_entry_id = body.entry_id
        plate_norm = None
    else:
        if not body.plate:
            raise HTTPException(422, "plate is required for mode=plate")
        plate_norm = worker.normalize_plate(body.plate)
        try:
            existing = _backend_get("/watchlist?subject_type=vehicle&active=true")
        except httpx.HTTPError as exc:
            raise HTTPException(502, f"Could not reach backend at {worker.INGEST_URL}: {exc}") from exc
        match = next(
            (e for e in existing["items"] if worker.normalize_plate(e["identifier"]) == plate_norm),
            None,
        )
        if match:
            target_entry_id = match["id"]
        else:
            try:
                created = _backend_post("/watchlist", {
                    "category": "wanted_vehicle",
                    "subject_type": "vehicle",
                    "identifier": body.plate.upper().strip(),
                    "severity": "high",
                    "description": "Added via Investigate — live plate watch",
                })
            except httpx.HTTPStatusError as exc:
                raise HTTPException(exc.response.status_code, exc.response.text) from exc
            target_entry_id = created["id"]

    job_id = uuid.uuid4().hex[:12]
    with _lock:
        for cid in body.camera_ids:
            _refcount[cid] = _refcount.get(cid, 0) + 1
            _start_camera_locked(cid)
        _jobs[job_id] = {
            "job_id": job_id,
            "mode": body.mode,
            "target_entry_id": target_entry_id,
            "plate": plate_norm,
            "camera_ids": body.camera_ids,
            "started_at": time.time(),
            "status": "running",
        }
    threading.Timer(JOB_TTL_S, _stop_job, args=[job_id]).start()
    log.info("job %s started: mode=%s target=%s cameras=%s", job_id, body.mode, target_entry_id, body.camera_ids)
    return dict(_jobs[job_id])


@app.post("/api/local/monitor/{job_id}/stop")
def monitor_stop(job_id: str):
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "Unknown job_id")
    return _stop_job(job_id) or job


@app.get("/api/local/monitor/status")
def monitor_status():
    with _lock:
        jobs = []
        for job in _jobs.values():
            cam_stats = []
            for cid in job["camera_ids"]:
                p = _pipelines.get(cid)
                cam_stats.append({
                    "camera_id": cid,
                    "running": p is not None,
                    "frames_processed": p.frames_processed if p else 0,
                    "faces_matched": p.faces_matched if p else 0,
                    "anpr_stats": dict(p.anpr_stats) if p else {},
                })
            jobs.append({**job, "cameras": cam_stats})
    return {"jobs": jobs}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=PORT)
