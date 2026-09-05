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

Env: SENTINEL_EMAIL + SENTINEL_PASSWORD (REQUIRED — the grid answers 401 to
     every RTSP connection without them),
     INGEST_URL (default http://localhost:8000), INGEST_API_KEY,
     CAMERA_IDS (comma-separated DB ids, default "1,6,12"),
     RTSP_BASE (default rtsp://103.250.160.189:8554/stream),
     SAMPLE_FPS (default 2.0), FACE_EVERY_S (default 15)
"""
from __future__ import annotations

import argparse
import base64
import logging
import os
import re
import threading
import time
from collections import Counter, defaultdict
from urllib.parse import quote

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
# The grid authenticates EVERY RTSP connection against the registered account,
# so these are required — without them the gateway answers 401 to DESCRIBE.
SENTINEL_EMAIL = os.environ.get("SENTINEL_EMAIL", "")
SENTINEL_PASSWORD = os.environ.get("SENTINEL_PASSWORD", "")
CAMERA_IDS = [int(c) for c in os.environ.get("CAMERA_IDS", "1,6,12").split(",") if c.strip()]
SAMPLE_FPS = float(os.environ.get("SAMPLE_FPS", "2.0"))        # inference rate per camera
FACE_EVERY_S = float(os.environ.get("FACE_EVERY_S", "15"))     # face pass cadence
PLATE_MIN_CONF = float(os.environ.get("PLATE_MIN_CONF", "0.5"))       # < this → discard (plan §5.2)
PLATE_MIN_WIDTH_PX = int(os.environ.get("PLATE_MIN_WIDTH_PX", "60"))  # plan §4 anpr_config
PLATE_CONF_HIGH = float(os.environ.get("PLATE_CONF_HIGH", "0.7"))     # >= this → high-confidence
PLATE_MIN_VOTES = int(os.environ.get("PLATE_MIN_VOTES", "2"))         # corroborating reads required
PLATE_VOTE_WINDOW_S = float(os.environ.get("PLATE_VOTE_WINDOW_S", "5.0"))
PLATE_STATIC_WINDOW_S = float(os.environ.get("PLATE_STATIC_WINDOW_S", "20.0"))
PLATE_STATIC_MIN_REPEATS = int(os.environ.get("PLATE_STATIC_MIN_REPEATS", "4"))
PLATE_STATIC_GRID_PX = int(os.environ.get("PLATE_STATIC_GRID_PX", "12"))
FACE_MATCH_THRESHOLD = float(os.environ.get("FACE_MATCH_THRESHOLD", "0.45"))
FACE_MIN_DETECT_CONF = float(os.environ.get("FACE_MIN_DETECT_CONF", "0.5"))
PUSH_DETECTION_EVERY_S = float(os.environ.get("PUSH_DETECTION_EVERY_S", "10"))
GALLERY_REFRESH_S = float(os.environ.get("GALLERY_REFRESH_S", "300"))

# Optional: save the exact frame a match happened on and reference it from the
# alert. Off by default (plain `worker.py run` behaves exactly as before — no
# behaviour change, no extra disk I/O) so this only activates when something
# (the local control server, for a demo) opts in by setting the directory.
LOCAL_SNAPSHOT_DIR = os.environ.get("LOCAL_SNAPSHOT_DIR", "")
LOCAL_SNAPSHOT_BASE_URL = os.environ.get(
    "LOCAL_SNAPSHOT_BASE_URL", "http://localhost:8800/local-frames"
).rstrip("/")

# Diagnostic-only, off by default: when set, every raw plate-OCR read (accepted
# AND rejected) saves its crop + logs the raw string, per-char confidences and
# crop width, capped at PLATE_DEBUG_MAX samples total across all cameras. This
# is how "rejected_format" was distinguished from a real near-miss vs. noise —
# see CLAUDE.md "Known limitation: live ANPR".
PLATE_DEBUG_DIR = os.environ.get("PLATE_DEBUG_DIR", "")
PLATE_DEBUG_MAX = int(os.environ.get("PLATE_DEBUG_MAX", "40"))
_plate_debug_lock = threading.Lock()
_plate_debug_count = 0


def plate_debug_sample(camera_id: int, crop_gray: np.ndarray, raw_text: str,
                        char_probs, ocr_conf: float, det_conf: float,
                        corrected: str | None, width_px: int) -> None:
    """Best-effort diagnostic dump of one raw OCR read — see PLATE_DEBUG_DIR."""
    global _plate_debug_count
    if not PLATE_DEBUG_DIR:
        return
    with _plate_debug_lock:
        if _plate_debug_count >= PLATE_DEBUG_MAX:
            return
        _plate_debug_count += 1
        idx = _plate_debug_count
    try:
        os.makedirs(PLATE_DEBUG_DIR, exist_ok=True)
        tag = f"{idx:03d}_{external_id(camera_id)}_w{width_px}"
        cv2.imwrite(os.path.join(PLATE_DEBUG_DIR, f"{tag}.jpg"), crop_gray)
        probs = [round(float(p), 3) for p in char_probs] if char_probs is not None else None
        with open(os.path.join(PLATE_DEBUG_DIR, "log.jsonl"), "a") as f:
            f.write(__import__("json").dumps({
                "idx": idx, "camera": external_id(camera_id), "width_px": width_px,
                "raw_text": raw_text, "char_probs": probs, "ocr_conf": round(ocr_conf, 3),
                "det_conf": round(det_conf, 3), "corrected": corrected,
            }) + "\n")
    except Exception:
        log.exception("plate_debug_sample failed")

# COCO classes: 2=car 3=motorcycle 5=bus 7=truck ; 0=person
VEHICLE_CLASSES = {2, 3, 5, 7}
PERSON_CLASSES = {0}
VEHICLE_TYPE_BY_CLASS = {2: "car", 3: "bike", 5: "bus", 7: "truck"}


def normalize_plate(text: str) -> str:
    return "".join(ch for ch in text.upper() if ch.isalnum())


# ── Indian plate validation + positional OCR correction (plan §5.1-5.3) ──────
#
# Format: [State:2 letters][District:2 digits][Series:1-3 letters][Number:1-4
# digits], e.g. GJ 01 AB 1234. The plan's own §5.3 stub admits it is
# unimplemented ("Simplified — full implementation uses positional logic");
# this replaces it. A digit sitting in a letter slot (or vice versa) is a
# well-known OCR confusion pair and must be corrected *by position*, never by
# a blind whole-string replace (a blind replace would mangle valid digits/
# letters that happen to share a lookalike).

PLATE_PATTERN = re.compile(r'^[A-Z]{2}\d{2}[A-Z]{1,3}\d{1,4}$')

# Real Indian state/UT RTO codes. Vehicles from any state legitimately pass
# through Gujarat cameras, so this is NOT restricted to GJ — but it does
# reject two-letter prefixes that are not a real state code, which catches a
# lot of OCR noise that would otherwise still "fit" the regex shape.
VALID_STATE_CODES = {
    "AN", "AP", "AR", "AS", "BR", "CH", "CG", "DD", "DL", "DN", "GA", "GJ",
    "HR", "HP", "JK", "JH", "KA", "KL", "LA", "LD", "MP", "MH", "MN", "ML",
    "MZ", "NL", "OD", "OR", "PY", "PB", "RJ", "SK", "TN", "TS", "TR", "UP",
    "UK", "UA", "WB",
}

# OCR lookalike pairs (plan §5.3): a character read in the wrong "slot" type
# gets mapped to its counterpart, never blindly across the whole string.
LETTER_TO_DIGIT = {"O": "0", "I": "1", "L": "1", "S": "5", "Z": "2",
                   "B": "8", "G": "6", "T": "7", "D": "0", "Q": "0"}
DIGIT_TO_LETTER = {"0": "O", "1": "I", "5": "S", "2": "Z",
                   "8": "B", "6": "G", "7": "T"}


def _fix_char(ch: str, want_digit: bool) -> str | None:
    """Coerce one OCR character into the type its plate slot expects."""
    if want_digit:
        return ch if ch.isdigit() else LETTER_TO_DIGIT.get(ch)
    return ch if ch.isalpha() else DIGIT_TO_LETTER.get(ch)


def _clean_plate_text(raw: str) -> str | None:
    """Positional correction + Indian-format validation of a raw OCR string.

    Tries every (series_len, number_len) split consistent with the plate
    grammar and the string's length, correcting each character by the type
    its position expects. Returns the corrected canonical plate (no spaces),
    preferring the split that needs the fewest corrections (ties broken
    toward the conventional 2-letter series), or None if the text cannot be
    coerced into a valid, real-state-coded Indian plate at all.
    """
    text = "".join(ch for ch in raw.upper() if ch.isalnum())
    if not (7 <= len(text) <= 11):
        return None

    best: tuple[tuple[int, int], str] | None = None
    for series_len in (1, 2, 3):
        for number_len in (1, 2, 3, 4):
            if 4 + series_len + number_len != len(text):
                continue
            slots = ([False, False] + [True, True] +
                     [False] * series_len + [True] * number_len)
            out = []
            cost = 0
            for ch, want_digit in zip(text, slots):
                fixed = _fix_char(ch, want_digit)
                if fixed is None:
                    break
                cost += fixed != ch
                out.append(fixed)
            else:
                corrected = "".join(out)
                if corrected[:2] not in VALID_STATE_CODES:
                    continue
                rank = (cost, 0 if series_len == 2 else 1)
                if best is None or rank < best[0]:
                    best = (rank, corrected)

    if best is None:
        return None
    corrected = best[1]
    return corrected if PLATE_PATTERN.match(corrected) else None


class _PlateVoter:
    """Multi-read voting + dedup for one camera (plan §5.2 'Multi-Read Voting').

    OCR reads of the *same* physical plate wobble slightly frame to frame.
    Rather than pushing every frame's independent guess, reads are clustered
    (exact length + small edit distance) within a short time window; a
    cluster is only released once it has been corroborated by enough reads,
    using the majority-voted spelling and the best confidence seen for it.
    """

    def __init__(self, window_s: float = PLATE_VOTE_WINDOW_S,
                 min_votes: int = PLATE_MIN_VOTES) -> None:
        self.window_s = window_s
        self.min_votes = min_votes
        self._clusters: list[dict] = []

    @staticmethod
    def _distance(a: str, b: str) -> int:
        """Levenshtein distance — no extra dependency, strings are short."""
        if a == b:
            return 0
        prev = list(range(len(b) + 1))
        for i, ca in enumerate(a, 1):
            cur = [i] + [0] * len(b)
            for j, cb in enumerate(b, 1):
                cur[j] = min(prev[j] + 1, cur[j - 1] + 1,
                             prev[j - 1] + (ca != cb))
            prev = cur
        return prev[-1]

    def add(self, text: str, ocr_conf: float, det_conf: float,
            now: float) -> tuple[str, float, float] | None:
        """Register one validated read. Returns (voted_text, best_ocr_conf,
        best_det_conf) once corroborated, else None (still buffering)."""
        self._clusters = [c for c in self._clusters
                          if now - c["last_ts"] <= self.window_s]
        cluster = None
        for c in self._clusters:
            rep = c["variants"].most_common(1)[0][0]
            max_dist = 1 if len(text) >= 7 else 0
            if len(text) == len(rep) and self._distance(text, rep) <= max_dist:
                cluster = c
                break
        if cluster is None:
            cluster = {"variants": Counter(), "last_ts": now,
                      "best_conf": 0.0, "best_det": det_conf}
            self._clusters.append(cluster)
        cluster["variants"][text] += 1
        cluster["last_ts"] = now
        if ocr_conf > cluster["best_conf"]:
            cluster["best_conf"] = ocr_conf
            cluster["best_det"] = det_conf
        if sum(cluster["variants"].values()) >= self.min_votes:
            voted_text = cluster["variants"].most_common(1)[0][0]
            return voted_text, cluster["best_conf"], cluster["best_det"]
        return None


def rtsp_url(camera_id: int) -> str:
    """Build the credentialed RTSP URL for a camera.

    Credentials go in the userinfo section because the gateway challenges every
    connection. The '@' in the email MUST be percent-encoded or it splits the
    userinfo from the host and the URL resolves to the wrong server.
    """
    base = RTSP_BASE.rstrip("/")
    authority = base.partition("://")[2].split("/", 1)[0]
    if SENTINEL_EMAIL and SENTINEL_PASSWORD and "@" not in authority:
        scheme, _, rest = base.partition("://")
        creds = f"{quote(SENTINEL_EMAIL, safe='')}:{quote(SENTINEL_PASSWORD, safe='')}"
        base = f"{scheme}://{creds}@{rest}"
    return f"{base}/cam{camera_id:02d}"


def redact(url: str) -> str:
    """Strip userinfo before a URL reaches the logs — errors echo the full URL."""
    return re.sub(r"//[^@/]+@", "//***:***@", url)


def external_id(camera_id: int) -> str:
    return f"cam{camera_id:02d}"


def save_snapshot(camera_id: int, frame: np.ndarray) -> str | None:
    """Persist the frame a match/detection happened on, return a fetchable URL.

    No-op (returns None) unless LOCAL_SNAPSHOT_DIR is set — see comment above.
    """
    if not LOCAL_SNAPSHOT_DIR:
        return None
    try:
        os.makedirs(LOCAL_SNAPSHOT_DIR, exist_ok=True)
        name = f"{external_id(camera_id)}_{int(time.time() * 1000)}.jpg"
        path = os.path.join(LOCAL_SNAPSHOT_DIR, name)
        cv2.imwrite(path, frame)
        return f"{LOCAL_SNAPSHOT_BASE_URL}/{name}"
    except Exception:
        log.exception("[%s] snapshot save failed", external_id(camera_id))
        return None


EVIDENCE_MAX_WIDTH = int(os.environ.get("EVIDENCE_MAX_WIDTH", "640"))
EVIDENCE_JPEG_QUALITY = int(os.environ.get("EVIDENCE_JPEG_QUALITY", "80"))


def draw_detection_boxes(frame: np.ndarray, boxes: list[dict]) -> np.ndarray:
    """Draw real bounding boxes on a COPY of the frame using OpenCV — genuine
    cv2.rectangle/putText annotation over the actual pixels the model ran
    inference on, not a mockup or a CSS overlay. This is what the Detection
    Viewer UI (frontend "Detections" page) displays: the same evidence image
    everywhere else, with the model's own bbox/class/confidence burned in.

    Each entry in `boxes`: {"bbox": (x1,y1,x2,y2), "label": str,
    "confidence": float | None, "color": (b,g,r) in OpenCV order}.
    """
    annotated = frame.copy()
    for box in boxes:
        x1, y1, x2, y2 = [int(v) for v in box["bbox"]]
        color = box.get("color", (0, 200, 0))
        cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
        label = box.get("label", "")
        conf = box.get("confidence")
        text = f"{label} {conf * 100:.0f}%" if conf is not None else label
        if not text:
            continue
        (tw, th), baseline = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        ty = max(y1, th + 6)
        cv2.rectangle(annotated, (x1, ty - th - 6), (x1 + tw + 6, ty + baseline - 2), color, -1)
        cv2.putText(annotated, text, (x1 + 3, ty - 3), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
    return annotated


def encode_evidence_b64(frame: np.ndarray) -> str | None:
    """Base64-JPEG the match frame for inline transport in the ingest payload.

    Unlike save_snapshot()'s local-file URL (only fetchable from the operator's
    own machine — fine for a same-machine demo, useless for anyone viewing the
    deployed Vercel/Render app from elsewhere), this travels with the alert
    itself through the real backend/DB and renders for any viewer, anywhere.
    Small and resized: only sent on an actual match/push, not every frame.
    """
    try:
        h, w = frame.shape[:2]
        if w > EVIDENCE_MAX_WIDTH:
            scale = EVIDENCE_MAX_WIDTH / w
            frame = cv2.resize(frame, (EVIDENCE_MAX_WIDTH, int(h * scale)))
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, EVIDENCE_JPEG_QUALITY])
        if not ok:
            return None
        return base64.b64encode(buf.tobytes()).decode("ascii")
    except Exception:
        log.exception("evidence encode failed")
        return None


APPEARANCE_HIST_BINS = (8, 8, 8)  # H, S, V


def vehicle_appearance_signature(frame: np.ndarray, bbox_xyxy) -> list[float] | None:
    """Cheap, real cross-camera vehicle appearance signature (plan §7.2
    Method 2 / "Key Differentiator #3: Multi-Strategy Vehicle Matching") for
    cameras that cannot read a plate at all (Tier B/C — see
    CAMERA_CAPABILITY_NOTES). Plan §23 spec'd OSNet/Torchreid for this, but
    that pulls another ~200MB dependency and a second heavy model onto a
    machine already running YOLOv8+InsightFace+plate-OCR; a normalized HSV
    color histogram of the vehicle crop is a genuine, real appearance
    signature — cheap enough to compute on every tracked vehicle — that
    correctly captures "same white hatchback vs. same black SUV" for the
    demo's actual need (narrowing candidates when ANPR is unavailable), even
    though it is weaker than a learned ReID embedding for near-identical
    vehicles of the same color/model.
    """
    try:
        x1, y1, x2, y2 = [max(0, int(v)) for v in bbox_xyxy]
        crop = frame[y1:y2, x1:x2]
        if crop.size == 0 or crop.shape[0] < 10 or crop.shape[1] < 10:
            return None
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        hist = cv2.calcHist([hsv], [0, 1, 2], None, list(APPEARANCE_HIST_BINS),
                             [0, 180, 0, 256, 0, 256])
        cv2.normalize(hist, hist, alpha=1.0, norm_type=cv2.NORM_L1)
        return [round(float(v), 5) for v in hist.flatten()]
    except Exception:
        log.exception("appearance signature failed")
        return None


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
            # 640x640 (plan §6.1's own reference value) measured live against
            # the real Sentinel Grid: on a genuine live frame from cam04 with
            # real pedestrians clearly visible, it found ZERO faces — the
            # people are simply too small once a 1920x1080 wide-intersection
            # frame is downscaled to 640. The exact same real frame, run
            # through SCRFD at det_size=(1280,1280), found 2 real faces at
            # legitimate confidence (0.67, 0.59) — the faces are genuinely
            # present, the detector just needed higher input resolution to
            # resolve them. The edge worker runs on a full local machine (not
            # the 512MB Render backend), so the extra compute is affordable.
            app.prepare(ctx_id=-1, det_size=(1280, 1280))
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
             vehicle_color: str | None = None, ts_ms: float | None = None,
             snapshot_ref: str | None = None, evidence_image: str | None = None,
             appearance_signature: list[float] | None = None) -> dict | None:
        payload = {
            "camera_id": camera_id,
            "plate_text": plate_text,
            "confidence": round(confidence, 3),
            "ocr_confidence": round(ocr_confidence, 3) if ocr_confidence else None,
            "vehicle_type": vehicle_type,
            "vehicle_color": vehicle_color,
            "snapshot_ref": snapshot_ref,
            "evidence_image": evidence_image,
            "appearance_signature": appearance_signature,
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
            r = self.client.get(
                f"{INGEST_URL}/api/v1/watchlist"
                "?subject_type=person&active=true&include_embeddings=true"
            )
            if r.status_code == 200:
                return r.json().get("items", [])
        except Exception as exc:
            log.warning("gallery fetch failed: %s", exc)
        return []

    def camera_config(self, camera_id: int) -> dict:
        """analytics_config for one camera — real per-camera capability audit
        (plate_readable/face_readable) where available, so the pipeline
        doesn't burn CPU (and risk OCR hallucination, see CLAUDE.md) running
        ANPR/face on a feed already confirmed illegible. Missing/unreachable
        defaults to {} → CameraPipeline treats that as "attempt both", the
        prior behaviour, so an unaudited or offline backend never silently
        disables anything.
        """
        try:
            r = self.client.get(f"{INGEST_URL}/api/v1/cameras/{camera_id}")
            if r.status_code == 200:
                return r.json().get("analytics_config") or {}
        except Exception as exc:
            log.warning("[%s] camera config fetch failed: %s", external_id(camera_id), exc)
        return {}


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
                 face_gallery: FaceGallery, video_source: str | int | None = None) -> None:
        """`video_source`, when given, replaces the Sentinel RTSP feed with a local
        file path or webcam device index (same idea, plan's "existing camera feed
        infrastructure" extended to local/offline sources for a demo where the
        Sentinel grid has no suitable footage for a given detection type)."""
        super().__init__(daemon=True, name=f"cam{camera_id:02d}")
        self.camera_id = camera_id
        self.ingest = ingest
        self.yolo_lock = yolo_lock
        self.face_gallery = face_gallery
        self.video_source = video_source
        self.models = MODELS
        self.tracker = sv.ByteTrack() if (MODELS.yolo and sv is not None) else None
        self._latest_frame: np.ndarray | None = None
        self._latest_pts: float | None = None
        self._frame_lock = threading.Lock()
        self._stop = threading.Event()
        self._last_plate_push: dict[str, float] = {}   # normalized plate → ts
        self._last_track_push: dict[str, float] = {}   # track key → ts
        self._last_face_pass = 0.0
        # Static-region false-positive guard (measured need, not a guess): the
        # plate DETECTOR (not the OCR) repeatedly fires on fixed background
        # text that happens to look plate-shaped — on-screen date/time overlay
        # digits, roadside "CENTER"-style signage — because that text never
        # moves frame to frame while a real plate (on a moving/arriving
        # vehicle) does. Measured on cam17: a signboard read as "CENTER" (OCR
        # conf 0.82-0.86, format-invalid) fired on ~30+ consecutive sampled
        # frames at an unchanged bbox, accounting for most of that camera's
        # rejected_format volume — a detection-stage false positive, not an
        # OCR failure. A box recurring at ~the same location repeatedly within
        # a short window is background, not a plate; skip OCR on it entirely.
        self._plate_box_hits: dict[tuple[int, int, int, int], list[float]] = {}
        self._backoff = 2.0
        self._plate_voter = _PlateVoter()
        self.anpr_stats: dict[str, int] = defaultdict(int)
        cfg = ingest.camera_config(camera_id)
        self.plate_readable = cfg.get("plate_readable", True)
        self.face_readable = cfg.get("face_readable", True)
        if not (self.plate_readable and self.face_readable):
            log.info("[%s] capability audit: plate_readable=%s face_readable=%s — skipping the other pass(es)",
                      external_id(camera_id), self.plate_readable, self.face_readable)
        # Live status counters, read by the local control server (job status).
        self.frames_processed = 0
        self.faces_matched = 0

    def stop(self) -> None:
        self._stop.set()

    # ── capture thread: always hold the newest frame (drops stale frames) ──
    def _capture_loop(self) -> None:
        if self.video_source is not None:
            self._capture_loop_local()
            return
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
                            external_id(self.camera_id), redact(str(exc)), self._backoff)
            if container is not None:
                try:
                    container.close()
                except Exception:
                    pass
            self._stop.wait(self._backoff)
            self._backoff = min(self._backoff * 2, 30.0)

    def _capture_loop_local(self) -> None:
        """Local file / webcam capture — mirrors the RTSP loop's semantics
        (always hold the newest frame) but loops a file back to frame 0
        instead of reconnecting, so a short demo clip behaves like a
        continuously-running camera (the same "loops at the end" behaviour
        integration.txt documents for the real Sentinel grid)."""
        is_device = isinstance(self.video_source, int)
        while not self._stop.is_set():
            cap = cv2.VideoCapture(self.video_source)
            if not cap.isOpened():
                log.warning("[%s] local source %s did not open — retry in %.0fs",
                            external_id(self.camera_id), self.video_source, self._backoff)
                cap.release()
                self._stop.wait(self._backoff)
                self._backoff = min(self._backoff * 2, 30.0)
                continue
            log.info("[%s] local source connected (%s)", external_id(self.camera_id), self.video_source)
            self._backoff = 2.0
            try:
                while not self._stop.is_set():
                    ok, frame = cap.read()
                    if not ok:
                        if is_device:
                            break  # real device drop — reconnect
                        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)  # file ended — loop
                        continue
                    with self._frame_lock:
                        self._latest_frame = frame
                        self._latest_pts = time.time() * 1000.0
                    self._stop.wait(1.0 / max(SAMPLE_FPS * 2, 1.0))  # don't spin faster than needed
            finally:
                cap.release()

    # ── helpers ──
    def _xyxy_to_bbox(self, xyxy) -> dict:
        x1, y1, x2, y2 = [float(v) for v in xyxy]
        return {"x": round(x1), "y": round(y1),
                "w": round(x2 - x1), "h": round(y2 - y1)}

    def _vehicle_match_at(self, plate_box, detections):
        """Find the vehicle detection (class + full bbox) whose box best
        contains the plate centre — used both for vehicle_type and for
        cropping the whole vehicle to compute an appearance signature.

        Indexes the parallel arrays rather than iterating: `sv.Detections`
        yields plain tuples when iterated, not per-detection objects.
        """
        if detections is None or len(detections) == 0:
            return None
        px, py, pw, ph = plate_box
        pcx, pcy = px + pw / 2, py + ph / 2
        best_cls, best_bbox, best_area = None, None, 0.0
        class_ids = getattr(detections, "class_id", None)
        if class_ids is None:
            return None
        for i in range(len(detections)):
            cls = int(class_ids[i])
            if cls not in VEHICLE_CLASSES:
                continue
            x1, y1, x2, y2 = [float(v) for v in detections.xyxy[i]]
            if x1 <= pcx <= x2 and y1 <= pcy <= y2:
                area = (x2 - x1) * (y2 - y1)
                if area > best_area:
                    best_area, best_cls, best_bbox = area, cls, (x1, y1, x2, y2)
        if best_cls is None:
            return None
        return VEHICLE_TYPE_BY_CLASS.get(best_cls), best_bbox

    def _is_static_plate_box(self, x1: int, y1: int, x2: int, y2: int, now: float) -> bool:
        """True if a plate-shaped box has fired at ~this location repeatedly
        within PLATE_STATIC_WINDOW_S — i.e. it's fixed background (OSD
        timestamp, signage) the detector keeps mistaking for a plate, not a
        vehicle passing through. See the comment on _plate_box_hits."""
        key = (round(x1 / PLATE_STATIC_GRID_PX), round(y1 / PLATE_STATIC_GRID_PX),
               round(x2 / PLATE_STATIC_GRID_PX), round(y2 / PLATE_STATIC_GRID_PX))
        hits = self._plate_box_hits.setdefault(key, [])
        hits.append(now)
        cutoff = now - PLATE_STATIC_WINDOW_S
        while hits and hits[0] < cutoff:
            hits.pop(0)
        # Bound memory on long runs: drop keys that have gone idle.
        if len(self._plate_box_hits) > 500:
            self._plate_box_hits = {k: v for k, v in self._plate_box_hits.items() if v}
        return len(hits) >= PLATE_STATIC_MIN_REPEATS

    def _maybe_push_plate(self, frame_ts: float | None, plate_text: str,
                          conf: float, ocr_conf: float, plate_box,
                          detections, frame: np.ndarray | None = None) -> None:
        """plate_text is already positionally-corrected + format-validated.

        Buffers into the per-camera voter (plan §5.2 multi-read voting); only
        pushes once a plate is corroborated, using the majority-voted
        spelling and best confidence seen for it. The existing 10s per-plate
        dedup still applies on top, so a parked vehicle doesn't spam events.
        """
        now = time.time()
        voted = self._plate_voter.add(plate_text, ocr_conf, conf, now)
        if voted is None:
            return  # not yet corroborated — buffered
        voted_text, best_ocr_conf, best_det_conf = voted

        norm = normalize_plate(voted_text)
        if len(norm) < 5:
            return
        if now - self._last_plate_push.get(norm, 0) < 10:   # dedupe 10s
            return
        self._last_plate_push[norm] = now
        self.anpr_stats["pushed"] += 1
        snap = save_snapshot(self.camera_id, frame) if frame is not None else None
        match = self._vehicle_match_at(plate_box, detections)
        vehicle_type, vehicle_bbox = match if match else (None, None)
        evidence = None
        if frame is not None:
            px, py, pw, ph = plate_box
            boxes = [{"bbox": (px, py, px + pw, py + ph), "label": f"PLATE {voted_text}",
                      "confidence": best_ocr_conf, "color": (0, 165, 255)}]
            if vehicle_bbox is not None:
                boxes.append({"bbox": vehicle_bbox, "label": vehicle_type or "vehicle",
                              "confidence": best_det_conf, "color": (0, 200, 0)})
            evidence = encode_evidence_b64(draw_detection_boxes(frame, boxes))
        appearance = (
            vehicle_appearance_signature(frame, vehicle_bbox)
            if frame is not None and vehicle_bbox is not None else None
        )
        result = self.ingest.anpr(
            camera_id=self.camera_id,
            plate_text=voted_text,
            confidence=best_det_conf,
            ocr_confidence=best_ocr_conf,
            vehicle_type=vehicle_type,
            ts_ms=frame_ts,
            snapshot_ref=snap,
            evidence_image=evidence,
            appearance_signature=appearance,
        )
        tier = "HIGH" if best_ocr_conf >= PLATE_CONF_HIGH else "LOW-CONF"
        if result:
            log.info("[%s] ANPR %s [%s] (ocr %.2f) → %s",
                     external_id(self.camera_id), voted_text, tier,
                     best_ocr_conf, result.get("status"))

    def _push_tracks(self, detections, frame: np.ndarray | None = None) -> None:
        """Push one metadata event per tracked vehicle/person, rate-limited.

        Indexes the parallel arrays rather than iterating: `sv.Detections`
        yields plain tuples when iterated, not per-detection objects.

        Vehicle events on a plate_readable=False camera (see the capability
        audit in seed_data.py) carry an appearance signature — this is the
        only signal available to correlate that vehicle with a plate-
        confirmed sighting elsewhere (plan §7.2 Method 2 / cross-camera ReID)
        since ANPR is already known to be futile here.
        """
        if detections is None or len(detections) == 0:
            return
        class_ids = getattr(detections, "class_id", None)
        if class_ids is None:
            return
        confidences = getattr(detections, "confidence", None)
        tracker_ids = getattr(detections, "tracker_id", None)
        now = time.time()
        for i in range(len(detections)):
            cls = int(class_ids[i])
            if cls not in VEHICLE_CLASSES and cls not in PERSON_CLASSES:
                continue
            track_id = int(tracker_ids[i]) if tracker_ids is not None else None
            key = str(track_id) if track_id is not None else f"raw-{cls}"
            if now - self._last_track_push.get(key, 0) < PUSH_DETECTION_EVERY_S:
                continue
            self._last_track_push[key] = now
            metadata: dict = {}
            if cls in VEHICLE_CLASSES and frame is not None and not self.plate_readable:
                sig = vehicle_appearance_signature(frame, detections.xyxy[i])
                if sig:
                    metadata["appearance_signature"] = sig
            if frame is not None:
                label = VEHICLE_TYPE_BY_CLASS.get(cls, "person" if cls in PERSON_CLASSES else "object")
                det_conf = float(confidences[i]) if confidences is not None else None
                annotated = draw_detection_boxes(frame, [{
                    "bbox": detections.xyxy[i], "label": label,
                    "confidence": det_conf,
                    "color": (0, 200, 0) if cls in VEHICLE_CLASSES else (255, 140, 0),
                }])
                evidence = encode_evidence_b64(annotated)
                if evidence:
                    metadata["evidence_image"] = evidence
            self.ingest.detection(
                camera_id=self.camera_id,
                event_type="person" if cls in PERSON_CLASSES else "vehicle",
                confidence=float(confidences[i]) if confidences is not None else 0.0,
                bbox=self._xyxy_to_bbox(detections.xyxy[i]),
                track_id=f"trk-{track_id}" if track_id is not None else None,
                metadata=metadata,
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
                self.faces_matched += 1
                snap = save_snapshot(self.camera_id, frame)
                annotated = draw_detection_boxes(frame, [{
                    "bbox": (x1, y1, x2, y2), "label": name,
                    "confidence": sim, "color": (0, 0, 220),
                }])
                evidence = encode_evidence_b64(annotated)
                metadata.update({"face_name": name,
                                 "matched_watchlist_id": entry_id,
                                 "similarity": round(sim, 3)})
                if snap:
                    metadata["snapshot_ref"] = snap
                if evidence:
                    metadata["evidence_image"] = evidence
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
                self.frames_processed += 1
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
                self._push_tracks(detections, frame=frame)

        # 2) ANPR — plate localization (YOLO) + OCR (fast-plate-ocr), plan §5
        if self.models.plate_det and self.models.plate_ocr and self.plate_readable:
            try:
                with self.yolo_lock:
                    plate_results = self.models.plate_det.predict(
                        rgb, conf=0.3, verbose=False)
                for pbox in plate_results[0].boxes:
                    conf = float(pbox.conf[0])
                    if conf < 0.35:
                        continue
                    x1, y1, x2, y2 = [int(v) for v in pbox.xyxy[0]]
                    if self._is_static_plate_box(x1, y1, x2, y2, time.time()):
                        self.anpr_stats["rejected_static"] += 1
                        continue
                    crop = frame[max(y1, 0):y2, max(x1, 0):x2]
                    if crop.size == 0:
                        continue
                    # plan §4 sets plate_min_width_px=60 for ANPR cameras, and
                    # this guard was missing. Below roughly that width there are
                    # not enough pixels per character to read, and the OCR does
                    # not fail cleanly — it hallucinates. Measured on real 35-64px
                    # crops from cam12: every preprocessing variant (upscale,
                    # CLAHE, Otsu, adaptive+denoise, sharpen) returned a DIFFERENT
                    # string for the same crop and zero passed format validation.
                    # Dropping these early saves CPU and keeps noise out of OCR.
                    if crop.shape[1] < PLATE_MIN_WIDTH_PX:
                        self.anpr_stats["rejected_too_small"] += 1
                        continue
                    # The pinned OCR model is single-channel. Passing a 3-channel
                    # BGR crop fails ONNX shape validation on the channel axis,
                    # which silently disabled ANPR for every frame.
                    crop_gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
                    preds = self.models.plate_ocr.run(crop_gray, return_confidence=True)
                    for pred in preds:
                        raw_text = pred.plate
                        ocr_conf = (
                            float(np.mean(pred.char_probs))
                            if pred.char_probs is not None and pred.char_probs.size
                            else conf
                        )
                        self.anpr_stats["raw"] += 1
                        # Confidence gate (plan §5.2): < 0.5 → discard outright.
                        # 0.5-0.7 is still buffered as "low confidence" (the
                        # real ocr_confidence value that goes out over the
                        # wire is what distinguishes it — no separate flag).
                        if ocr_conf < PLATE_MIN_CONF:
                            self.anpr_stats["discarded_conf"] += 1
                            plate_debug_sample(self.camera_id, crop_gray, raw_text,
                                                pred.char_probs, ocr_conf, conf, None,
                                                crop.shape[1])
                            continue
                        corrected = _clean_plate_text(raw_text)
                        if corrected is None:
                            self.anpr_stats["rejected_format"] += 1
                            plate_debug_sample(self.camera_id, crop_gray, raw_text,
                                                pred.char_probs, ocr_conf, conf, None,
                                                crop.shape[1])
                            log.debug("[%s] ANPR reject (format) raw=%r ocr=%.2f",
                                      external_id(self.camera_id), raw_text, ocr_conf)
                            continue
                        plate_debug_sample(self.camera_id, crop_gray, raw_text,
                                            pred.char_probs, ocr_conf, conf, corrected,
                                            crop.shape[1])
                        self.anpr_stats["validated"] += 1
                        self._maybe_push_plate(
                            frame_ts, corrected, conf, ocr_conf,
                            (x1, y1, x2 - x1, y2 - y1),
                            detections if detections is not None else [],
                            frame=frame)
            except Exception:
                log.exception("[%s] plate pass failed", external_id(self.camera_id))

        # 3) Face recognition (plan §6) — cadence-limited
        if self.models.face_app and self.face_readable and time.time() - self._last_face_pass >= FACE_EVERY_S:
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
            for p in pipelines:
                log.info("[%s] anpr funnel: %s",
                         external_id(p.camera_id), dict(p.anpr_stats))
    except KeyboardInterrupt:
        log.info("shutting down…")
        for p in pipelines:
            p.stop()


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
            log.info("PyAV failed (%s) — trying OpenCV", redact(str(exc)))
    if frame is None:
        cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
        for _ in range(150):  # up to ~15s for first IDR (mixed H.264/H.265 joins)
            ok, frame = cap.read()
            if ok:
                break
            time.sleep(0.1)
        cap.release()
    if frame is None:
        raise SystemExit(
            f"no frame from {redact(url)}"
            + ("" if (SENTINEL_EMAIL and SENTINEL_PASSWORD) else
               " — SENTINEL_EMAIL/SENTINEL_PASSWORD are unset, so the gateway "
               "will answer 401 to every request")
        )
    cv2.imwrite(out, frame)
    log.info("saved %s (%dx%d) from %s", out, frame.shape[1], frame.shape[0], redact(url))


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
