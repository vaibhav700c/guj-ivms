"""Real ANPR + detection analytics worker — edge/regional node (plan §5, §6, §7).

This is the actual ML inference pipeline (Week 2 of the hackathon plan):

    Sentinel RTSP (TCP) ──▶ OpenCV capture ──▶ YOLOv8 (ultralytics)
                              │                     │
                              │               ByteTrack (supervision)
                              │                     │
                              ├──▶ fast-plate-ocr (plate detect + OCR, ONNX)
                              └──▶ InsightFace ArcFace embeddings (optional)

    structured metadata ──▶ POST /api/v1/ingest/{anpr,detection} ──▶ central
    platform correlation (watchlist → alerts). Raw video never leaves the edge.

Implements the integration contract (integration.txt):
  * RTSP forced over TCP (UDP across NAT produces corrupt frames)
  * reconnect with exponential backoff (2s → 30s cap), never tight-loop
  * timing from frame PTS where available, never CAP_PROP_FPS
  * inter-frame gaps tolerated; join-time decoder warnings logged, not fatal

Install (Python 3.11/3.12):
    cd analytics && python3.12 -m venv .venv
    .venv/bin/pip install -r requirements.txt

Run:
    .venv/bin/python worker.py test-rtsp --camera 1     # grab one frame
    .venv/bin/python worker.py enroll --entry-id 6 --image face.jpg
    .venv/bin/python worker.py run                      # live pipeline

Env: INGEST_URL (default http://localhost:8000), INGEST_API_KEY,
     CAMERA_IDS (comma-separated DB ids, default "1,6,12"),
     RTSP_BASE (default rtsp://103.250.160.189:8554/stream),
     SAMPLE_FPS (default 2.0), FACE_EVERY_S (default 15)
"""
from __future__ import annotations

import argparse
import logging
import os
import threading
import time
from collections import defaultdict

import cv2
import httpx
import numpy as np

try:
    import supervision as sv  # ByteTrack tracker
except Exception:  # pragma: no cover - optional module
    sv = None

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("analytics-worker")

# ── Configuration ─────────────────────────────────────────────────────────────

INGEST_URL = os.environ.get("INGEST_URL", "http://localhost:8000").rstrip("/")
INGEST_API_KEY = os.environ.get("INGEST_API_KEY", "")
RTSP_BASE = os.environ.get("RTSP_BASE", "rtsp://103.250.160.189:8554/stream")
CAMERA_IDS = [int(c) for c in os.environ.get("CAMERA_IDS", "1,6,12").split(",") if c.strip()]
SAMPLE_FPS = float(os.environ.get("SAMPLE_FPS", "2.0"))        # inference rate per camera
FACE_EVERY_S = float(os.environ.get("FACE_EVERY_S", "15"))     # face pass cadence
PLATE_MIN_CONF = float(os.environ.get("PLATE_MIN_CONF", "0.55"))
FACE_MATCH_THRESHOLD = float(os.environ.get("FACE_MATCH_THRESHOLD", "0.45"))
FACE_MIN_DETECT_CONF = float(os.environ.get("FACE_MIN_DETECT_CONF", "0.5"))
PUSH_DETECTION_EVERY_S = float(os.environ.get("PUSH_DETECTION_EVERY_S", "10"))
GALLERY_REFRESH_S = float(os.environ.get("GALLERY_REFRESH_S", "300"))

# COCO classes: 2=car 3=motorcycle 5=bus 7=truck ; 0=person
VEHICLE_CLASSES = {2, 3, 5, 7}
PERSON_CLASSES = {0}
VEHICLE_TYPE_BY_CLASS = {2: "car", 3: "bike", 5: "bus", 7: "truck"}


def normalize_plate(text: str) -> str:
    return "".join(ch for ch in text.upper() if ch.isalnum())


def rtsp_url(camera_id: int) -> str:
    return f"{RTSP_BASE}/cam{camera_id:02d}"


def external_id(camera_id: int) -> str:
    return f"cam{camera_id:02d}"


# ── Model loading (graceful degradation per module) ──────────────────────────

class Models:
    """Loads the ML stack; each module degrades independently."""

    def __init__(self) -> None:
        self.yolo = None
        self.plate_det = None
        self.plate_ocr = None
        self.face_app = None
        self.av = None
        try:
            import av as _av

            self.av = _av
        except Exception:
            log.warning("PyAV not available — falling back to OpenCV RTSP capture")
        self._load_yolo()
        self._load_plate()
        self._load_face()

    def _load_yolo(self) -> None:
        try:
            from ultralytics import YOLO

            self.yolo = YOLO("yolov8n.pt")  # auto-downloads ~6 MB COCO weights
            log.info("YOLOv8n loaded — vehicle/person detection enabled")
        except Exception:
            log.exception("YOLO load failed — detection disabled")

    def _load_plate(self) -> None:
        """Plate detection (YOLOv8n license-plate) + OCR (fast-plate-ocr, ONNX CPU).

        fast-plate-ocr ships the OCR recognizer only; plate localization uses a
        YOLOv8n detector trained on license plates (auto-downloaded weights).
        """
        try:
            local = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "weights", "yolov8n-license-plate.pt")
            src = local if os.path.exists(local) else (
                "https://huggingface.co/maazsajid/license-plate-yolov8/resolve/main/best.pt")
            self.plate_det = self.yolo.__class__(src)
            from fast_plate_ocr import LicensePlateRecognizer

            self.plate_ocr = LicensePlateRecognizer(
                hub_ocr_model="global-plates-mobile-vit-v2-model", device="cpu"
            )
            log.info("plate detector + fast-plate-ocr loaded — ANPR enabled")
        except Exception:
            self.plate_det = None
            self.plate_ocr = None
            log.exception("plate pipeline load failed — ANPR disabled (detections still push)")

    def _load_face(self) -> None:
        try:
            from insightface.app import FaceAnalysis

            app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
            app.prepare(ctx_id=-1, det_size=(640, 640))
            self.face_app = app
            log.info("InsightFace buffalo_l loaded — face recognition enabled")
        except Exception:
            log.exception("InsightFace load failed — face module disabled "
                          "(pip install insightface onnxruntime)")


MODELS = Models()

# ── Ingest client ─────────────────────────────────────────────────────────────

class Ingest:
    """Central-platform push client — Model 3 federation contract."""

    def __init__(self) -> None:
        headers = {"X-API-Key": INGEST_API_KEY} if INGEST_API_KEY else {}
        self.client = httpx.Client(timeout=15, headers=headers)
        self.stats = defaultdict(int)

    def _post(self, path: str, payload: dict) -> dict | None:
        try:
            r = self.client.post(f"{INGEST_URL}/api/v1/ingest/{path}", json=payload)
            if r.status_code in (200, 201):
                self.stats[path] += 1
                return r.json()
            log.warning("ingest %s → HTTP %d %s", path, r.status_code, r.text[:150])
        except Exception as exc:
            log.warning("ingest %s failed: %s", path, exc)
        return None

    def anpr(self, camera_id: int, plate_text: str, confidence: float,
             ocr_confidence: float | None = None, vehicle_type: str | None = None,
             vehicle_color: str | None = None, ts_ms: float | None = None) -> dict | None:
        payload = {
            "camera_id": camera_id,
            "plate_text": plate_text,
            "confidence": round(confidence, 3),
            "ocr_confidence": round(ocr_confidence, 3) if ocr_confidence else None,
            "vehicle_type": vehicle_type,
            "vehicle_color": vehicle_color,
            "source": "edge-yolo",
        }
        if ts_ms:
            from datetime import datetime, timezone
            payload["timestamp"] = datetime.fromtimestamp(
                ts_ms / 1000.0, tz=timezone.utc).isoformat()
        return self._post("anpr", payload)

    def detection(self, camera_id: int, event_type: str, confidence: float,
                  bbox: dict | None = None, metadata: dict | None = None,
                  track_id: str | None = None) -> dict | None:
        return self._post("detection", {
            "camera_id": camera_id,
            "event_type": event_type,
            "track_id": track_id,
            "confidence": round(confidence, 3),
            "bbox": bbox or {},
            "metadata": metadata or {},
            "source": "edge-yolo",
        })

    def watchlist_persons(self) -> list[dict]:
        try:
            r = self.client.get(f"{INGEST_URL}/api/v1/watchlist?subject_type=person&active=true")
            if r.status_code == 200:
                return r.json().get("items", [])
        except Exception as exc:
            log.warning("gallery fetch failed: %s", exc)
        return []


# ── Face gallery (plan §6 — real ArcFace embeddings + cosine search) ─────────

class FaceGallery:
    """Cosine-similarity search against watchlist persons with enrolled embeddings."""

    def __init__(self, ingest: Ingest) -> None:
        self.ingest = ingest
        self.gallery: list[tuple[int, str, np.ndarray]] = []  # (entry_id, name, 512-d)
        self._last_refresh = 0.0

    def refresh(self, force: bool = False) -> None:
        now = time.time()
        if not force and now - self._last_refresh < GALLERY_REFRESH_S:
            return
        self._last_refresh = now
        items = self.ingest.watchlist_persons()
        gallery = []
        for item in items:
            ref = item.get("reference_embedding")
            if ref and len(ref) >= 64:
                gallery.append((item["id"], item["identifier"],
                                np.asarray(ref, dtype=np.float32)))
        if gallery:
            log.info("face gallery: %d enrolled watchlist person(s)", len(gallery))
        self.gallery = gallery

    def search(self, embedding: np.ndarray) -> tuple[int, str, float] | None:
        self.refresh()
        if not self.gallery:
            return None
        best_id, best_name, best_sim = None, None, -1.0
        for entry_id, name, ref in self.gallery:
            denom = float(np.linalg.norm(embedding) * np.linalg.norm(ref) + 1e-9)
            sim = float(np.dot(embedding, ref)) / denom
            if sim > best_sim:
                best_id, best_name, best_sim = entry_id, name, sim
        if best_sim >= FACE_MATCH_THRESHOLD:
            return best_id, best_name, best_sim
        return None


# ── Per-camera pipeline (plan §5: detection → tracking → ANPR) ───────────────

class CameraPipeline(threading.Thread):
    """One RTSP source: capture thread + inference loop (latest-frame semantics)."""

    def __init__(self, camera_id: int, ingest: Ingest, yolo_lock: threading.Lock,
                 face_gallery: FaceGallery) -> None:
        super().__init__(daemon=True, name=f"cam{camera_id:02d}")
        self.camera_id = camera_id
        self.ingest = ingest
        self.yolo_lock = yolo_lock
        self.face_gallery = face_gallery
        self.models = MODELS
        self.tracker = sv.ByteTrack() if (MODELS.yolo and sv is not None) else None
        self._latest_frame: np.ndarray | None = None
        self._latest_pts: float | None = None
        self._frame_lock = threading.Lock()
        self._stop = threading.Event()
        self._last_plate_push: dict[str, float] = {}   # normalized plate → ts
        self._last_track_push: dict[str, float] = {}   # track key → ts
        self._last_face_pass = 0.0
        self._backoff = 2.0

    # ── capture thread: always hold the newest frame (drops stale frames) ──
    def _capture_loop(self) -> None:
        url = rtsp_url(self.camera_id)
        # integration.txt §2: force TCP — UDP across NAT yields corrupt frames
        os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")
        while not self._stop.is_set():
            container = None
            try:
                if self.models.av is not None:
                    # PyAV / FFmpeg — the only reliably-working RTSP client in
                    # this env (OpenCV's bundled ffmpeg fails gortsplib SETUP/PLAY).
                    container = self.models.av.open(url, options={
                        "rtsp_transport": "tcp",
                        "stimeout": "15000000",  # 15s connect/IO timeout (µs)
                    })
                    log.info("[%s] RTSP connected (TCP via FFmpeg)", external_id(self.camera_id))
                    self._backoff = 2.0
                    for frame in container.decode(video=0):
                        if self._stop.is_set():
                            break
                        img = frame.to_ndarray(format="bgr24")
                        pts_ms = None
                        if frame.pts is not None:
                            pts_ms = round(frame.pts * frame.time_base * 1000.0, 1)
                        with self._frame_lock:
                            self._latest_frame = img
                            self._latest_pts = pts_ms if pts_ms and pts_ms > 0 else None
                else:
                    cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
                    if not cap.isOpened():
                        raise ConnectionError("cv2 VideoCapture open failed")
                    log.info("[%s] RTSP connected (OpenCV)", external_id(self.camera_id))
                    self._backoff = 2.0
                    try:
                        while not self._stop.is_set():
                            ok, frame = cap.read()
                            if not ok:
                                break
                            with self._frame_lock:
                                self._latest_frame = frame
                                pts = cap.get(cv2.CAP_PROP_POS_MSEC)
                                self._latest_pts = pts if pts and pts > 0 else None
                    finally:
                        cap.release()
            except Exception as exc:
                log.warning("[%s] stream error: %s — retry in %.0fs",
                            external_id(self.camera_id), exc, self._backoff)
            if container is not None:
                try:
                    container.close()
                except Exception:
                    pass
            self._stop.wait(self._backoff)
            self._backoff = min(self._backoff * 2, 30.0)

    # ── helpers ──
    def _xyxy_to_bbox(self, xyxy) -> dict:
        x1, y1, x2, y2 = [float(v) for v in xyxy]
        return {"x": round(x1), "y": round(y1),
                "w": round(x2 - x1), "h": round(y2 - y1)}

    def _vehicle_type_at(self, plate_box, detections) -> str | None:
        """Assign the vehicle class whose box best contains the plate centre."""
        px, py, pw, ph = plate_box
        pcx, pcy = px + pw / 2, py + ph / 2
        best, best_area = None, 0
        for det in detections:
            if det.class_id[0] not in VEHICLE_CLASSES:
                continue
            x1, y1, x2, y2 = det.xyxy[0]
            if x1 <= pcx <= x2 and y1 <= pcy <= y2:
                area = (x2 - x1) * (y2 - y1)
                if area > best_area:
                    best_area, best = area, det.class_id[0]
        return VEHICLE_TYPE_BY_CLASS.get(best)

    def _maybe_push_plate(self, frame_ts: float | None, plate_text: str,
                          conf: float, ocr_conf: float, plate_box,
                          detections) -> None:
        norm = normalize_plate(plate_text)
        if len(norm) < 5:
            return
        now = time.time()
        if now - self._last_plate_push.get(norm, 0) < 10:   # dedupe 10s
            return
        self._last_plate_push[norm] = now
        result = self.ingest.anpr(
            camera_id=self.camera_id,
            plate_text=plate_text,
            confidence=conf,
            ocr_confidence=ocr_conf,
            vehicle_type=self._vehicle_type_at(plate_box, detections),
            ts_ms=frame_ts,
        )
        if result:
            log.info("[%s] ANPR %s (ocr %.2f) → %s",
                     external_id(self.camera_id), plate_text, ocr_conf,
                     result.get("status"))

    def _push_tracks(self, detections) -> None:
        now = time.time()
        for det in detections:
            cls = det.class_id[0]
            if cls not in VEHICLE_CLASSES and cls not in PERSON_CLASSES:
                continue
            track_id = int(det.tracker_id[0]) if det.tracker_id is not None else None
            key = str(track_id) if track_id is not None else f"raw-{cls}"
            if now - self._last_track_push.get(key, 0) < PUSH_DETECTION_EVERY_S:
                continue
            self._last_track_push[key] = now
            self.ingest.detection(
                camera_id=self.camera_id,
                event_type="person" if cls in PERSON_CLASSES else "vehicle",
                confidence=float(det.confidence[0]),
                bbox=self._xyxy_to_bbox(det.xyxy[0]),
                track_id=f"trk-{track_id}" if track_id is not None else None,
            )

    def _face_pass(self, frame: np.ndarray) -> None:
        """Real face pipeline: SCRFD detect → ArcFace 512-d → gallery cosine search."""
        if not self.models.face_app:
            return
        try:
            faces = self.models.face_app.get(frame)
        except Exception:
            log.exception("[%s] face pass failed", external_id(self.camera_id))
            return
        for face in faces:
            conf = float(getattr(face, "det_score", 1.0))
            if conf < FACE_MIN_DETECT_CONF:
                continue
            emb = face.normed_embedding
            x1, y1, x2, y2 = [float(v) for v in face.bbox[:4]]
            bbox = {"x": round(x1), "y": round(y1),
                    "w": round(x2 - x1), "h": round(y2 - y1)}
            metadata: dict = {"embedding": [round(float(v), 5) for v in emb.tolist()]}
            match = self.face_gallery.search(emb)
            if match:
                entry_id, name, sim = match
                metadata.update({"face_name": name,
                                 "matched_watchlist_id": entry_id,
                                 "similarity": round(sim, 3)})
                log.info("[%s] FACE MATCH %s (cos %.2f) → alert path",
                         external_id(self.camera_id), name, sim)
            self.ingest.detection(
                camera_id=self.camera_id, event_type="face",
                confidence=conf, bbox=bbox, metadata=metadata,
            )

    # ── main inference loop ──
    def run(self) -> None:
        threading.Thread(target=self._capture_loop, daemon=True,
                         name=f"cam{self.camera_id:02d}-capture").start()
        interval = 1.0 / max(SAMPLE_FPS, 0.1)
        log.info("[%s] pipeline started (sample %.1f fps, ANPR=%s, face=%s)",
                 external_id(self.camera_id), SAMPLE_FPS,
                 bool(self.models.plate_ocr), bool(self.models.face_app))
        while not self._stop.is_set():
            loop_start = time.time()
            with self._frame_lock:
                frame = None if self._latest_frame is None else self._latest_frame.copy()
                frame_ts = self._latest_pts
            if frame is None:
                self._stop.wait(1.0)
                continue
            try:
                self._process_frame(frame, frame_ts)
            except Exception:
                log.exception("[%s] inference tick failed", external_id(self.camera_id))
            elapsed = time.time() - loop_start
            self._stop.wait(max(interval - elapsed, 0.01))   # pace to SAMPLE_FPS

    def _process_frame(self, frame: np.ndarray, frame_ts: float | None) -> None:
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        # 1) YOLO detection + ByteTrack (plan §5 stages 2-3)
        detections = None
        if self.models.yolo:
            with self.yolo_lock:  # one shared model across camera threads
                results = self.models.yolo.predict(
                    rgb, classes=list(VEHICLE_CLASSES | PERSON_CLASSES),
                    conf=0.35, verbose=False,
                )
            r = results[0]
            detections = sv.Detections.from_ultralytics(r)
            if self.tracker is not None and len(detections) > 0:
                detections = self.tracker.update_with_detections(detections)
            if len(detections) > 0:
                self._push_tracks(detections)

        # 2) ANPR — plate localization (YOLO) + OCR (fast-plate-ocr), plan §5
        if self.models.plate_det and self.models.plate_ocr:
            try:
                with self.yolo_lock:
                    plate_results = self.models.plate_det.predict(
                        rgb, conf=0.3, verbose=False)
                for pbox in plate_results[0].boxes:
                    conf = float(pbox.conf[0])
                    if conf < 0.35:
                        continue
                    x1, y1, x2, y2 = [int(v) for v in pbox.xyxy[0]]
                    crop = frame[max(y1, 0):y2, max(x1, 0):x2]
                    if crop.size == 0:
                        continue
                    preds = self.models.plate_ocr.run(crop, return_confidence=True)
                    for pred in preds:
                        text = pred.plate
                        ocr_conf = (
                            float(np.mean(pred.char_probs))
                            if pred.char_probs is not None and pred.char_probs.size
                            else conf
                        )
                        if ocr_conf < PLATE_MIN_CONF or len(text) < 5:
                            continue
                        self._maybe_push_plate(
                            frame_ts, text, conf, ocr_conf,
                            (x1, y1, x2 - x1, y2 - y1),
                            detections if detections is not None else [])
            except Exception:
                log.exception("[%s] plate pass failed", external_id(self.camera_id))

        # 3) Face recognition (plan §6) — cadence-limited
        if self.models.face_app and time.time() - self._last_face_pass >= FACE_EVERY_S:
            self._last_face_pass = time.time()
            self._face_pass(frame)


# ── CLI commands ──────────────────────────────────────────────────────────────

def cmd_run(args) -> None:
    ingest = Ingest()
    gallery = FaceGallery(ingest)
    gallery.refresh(force=True)
    yolo_lock = threading.Lock()
    pipelines = [CameraPipeline(cid, ingest, yolo_lock, gallery) for cid in CAMERA_IDS]
    log.info("worker running — cameras %s → %s (modules: yolo=%s anpr=%s face=%s)",
             [external_id(c) for c in CAMERA_IDS], INGEST_URL,
             bool(MODELS.yolo), bool(MODELS.plate_ocr), bool(MODELS.face_app))
    for p in pipelines:
        p.start()
    try:
        while True:
            time.sleep(60)
            log.info("stats: %s", dict(ingest.stats))
    except KeyboardInterrupt:
        log.info("shutting down…")
        for p in pipelines:
            p._stop.set()


def cmd_test_rtsp(args) -> None:
    """Grab one real frame — proves RTSP source + decode path (integration.txt §2)."""
    url = rtsp_url(args.camera)
    os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")
    out = args.out or f"/tmp/frame_cam{args.camera:02d}.jpg"
    frame = None
    if MODELS.av is not None:
        try:
            container = MODELS.av.open(url, options={
                "rtsp_transport": "tcp", "stimeout": "15000000"})
            for raw in container.decode(video=0):
                frame = raw.to_ndarray(format="bgr24")
                break
            container.close()
        except Exception as exc:
            log.info("PyAV failed (%s) — trying OpenCV", exc)
    if frame is None:
        cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
        for _ in range(150):  # up to ~15s for first IDR (mixed H.264/H.265 joins)
            ok, frame = cap.read()
            if ok:
                break
            time.sleep(0.1)
        cap.release()
    if frame is None:
        raise SystemExit(f"no frame from {url}")
    cv2.imwrite(out, frame)
    log.info("saved %s (%dx%d) from %s", out, frame.shape[1], frame.shape[0], url)


def cmd_enroll(args) -> None:
    """Compute an ArcFace embedding for a reference photo → store on watchlist entry."""
    if not MODELS.face_app:
        raise SystemExit("InsightFace not available — pip install insightface onnxruntime")
    img = cv2.imread(args.image)
    if img is None:
        raise SystemExit(f"cannot read {args.image}")
    faces = MODELS.face_app.get(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    if not faces:
        raise SystemExit("no face found in image")
    emb = [round(float(v), 5) for v in faces[0].normed_embedding.tolist()]
    headers = {"X-API-Key": INGEST_API_KEY} if INGEST_API_KEY else {}
    r = httpx.post(f"{INGEST_URL}/api/v1/watchlist/{args.entry_id}/enroll-face",
                   json={"embedding": emb}, headers=headers, timeout=15)
    r.raise_for_status()
    log.info("enrolled entry %d (%d-dim embedding): %s", args.entry_id, len(emb), r.json())


def main() -> None:
    parser = argparse.ArgumentParser(description="Gujarat IVMS edge analytics worker")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run", help="live pipeline over RTSP → ingest API").set_defaults(func=cmd_run)
    t = sub.add_parser("test-rtsp", help="grab one frame from a camera")
    t.add_argument("--camera", type=int, default=1)
    t.add_argument("--out", default=None)
    t.set_defaults(func=cmd_test_rtsp)
    e = sub.add_parser("enroll", help="enroll a face photo onto a watchlist person")
    e.add_argument("--entry-id", type=int, required=True)
    e.add_argument("--image", required=True)
    e.set_defaults(func=cmd_enroll)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
