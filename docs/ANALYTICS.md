# Real ML Analytics Pipeline — Edge Worker

Implementation of plan **§5 (ANPR pipeline)**, **§6 (face recognition)** and
**§7 (vehicle tracking)** — the actual inference stack, not simulation.

```
Sentinel RTSP (TCP) ──▶ OpenCV capture ──▶ YOLOv8n (ultralytics)
        cam01…cam30          │                    │
                             │              ByteTrack (supervision)
                             │                    │
                             ├──▶ fast-plate-ocr  ── plate text + OCR conf
                             └──▶ InsightFace     ── face det + 512-d ArcFace
                                  (optional)

        structured metadata only ──▶ POST /api/v1/ingest/{anpr,detection}
                                     ──▶ watchlist correlation ──▶ alerts
```

**Raw video never leaves the edge node** — only plate strings, bboxes,
confidences and embeddings flow to the central platform (plan §1 principle).

## Modules & graceful degradation

| Module | Package | Model | Degrades to |
|---|---|---|---|
| Vehicle/person detection | `ultralytics` | YOLOv8n (COCO, auto-download ~6 MB) | worker still runs plate pass |
| Multi-object tracking | `supervision` | ByteTrack | raw detections (no track IDs) |
| ANPR (plate detect + OCR) | `fast-plate-ocr` | YOLOv9-t plate detector + COCR (ONNX, CPU) | detections-only events |
| Face recognition | `insightface` *(optional)* | SCRFD + ArcFace `buffalo_l` (~330 MB) | face events disabled |

> Note: the plan named PaddleOCR for plate OCR. `fast-plate-ocr` was chosen as
> the production OCR because it is a single small ONNX model purpose-built for
> license plates (10× lighter than PaddleOCR, no paddlepaddle dependency), and
> follows the same detect→rectify→OCR contract as plan §5. Swapping in
> PaddleOCR later only touches `Models._load_plate()` / `_process_frame()`.

## Integration contract compliance (`integration.txt`)

- RTSP forced over TCP (`OPENCV_FFMPEG_CAPTURE_OPTIONS=rtsp_transport;tcp`)
- Reconnect with exponential backoff, 2 s → 30 s cap, never tight-loop
- Frame timestamps from PTS (`CAP_PROP_POS_MSEC`), never `CAP_PROP_FPS`
- Inter-frame gaps tolerated → logged reconnect, no crash
- Join-time decoder warnings non-fatal (retry window for first IDR)
- Camera list is configuration, not hard-coded (`CAMERA_IDS` env var)
- Latest-frame semantics: capture always holds the newest frame, inference
  never falls behind real time

## Face recognition & watchlist enrollment (plan §6)

1. Compute a reference ArcFace embedding from any photo of the person:
   ```bash
   .venv/bin/python worker.py enroll --entry-id 6 --image suspect.jpg
   ```
   → stores the 512-d embedding on the watchlist entry
   (`POST /api/v1/watchlist/{id}/enroll-face`).
2. The live pipeline detects faces (SCRFD), computes ArcFace embeddings and
   matches against the enrolled gallery by cosine similarity (threshold 0.45).
3. Matches push `ingest/detection` events carrying the embedding + match;
   the central correlation engine raises a `watchlist_person` alert and
   broadcasts it over WebSocket in real time.

The backend correlation engine (`alert_engine.evaluate_person_event`) supports
three tiers: trusted on-device match (`matched_watchlist_id`), center-side
cosine match against enrolled embeddings, and the demo token fallback used by
the simulator.

## Run it

```bash
cd analytics
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
# optional face recognition:
.venv/bin/pip install insightface

# 1. prove the video source (no ML needed)
.venv/bin/python worker.py test-rtsp --camera 1        # → /tmp/frame_cam01.jpg

# 2. enroll faces for watchlist persons (optional)
.venv/bin/python worker.py enroll --entry-id 6 --image face.jpg

# 3. run the live pipeline
export $(grep -v '^#' .env | xargs)   # INGEST_URL, INGEST_API_KEY, CAMERA_IDS…
.venv/bin/python worker.py run
```

Or with Docker:

```bash
cd guj-ivms
docker compose --profile analytics up --build analytics
```

Config via env vars (or `analytics/.env`, gitignored):

| Var | Default | Meaning |
|---|---|---|
| `INGEST_URL` | `http://localhost:8000` | Central platform base URL |
| `INGEST_API_KEY` | *(empty)* | Federation key — required when the backend sets one |
| `CAMERA_IDS` | `1,6,12` | DB camera ids (Tier A cameras 6, 7, 12 per plan §20) |
| `RTSP_BASE` | `rtsp://103.250.160.189:8554/stream` | Sentinel RTSP gateway |
| `SAMPLE_FPS` | `2.0` | Inference rate per camera (CPU-friendly) |
| `FACE_EVERY_S` | `15` | Seconds between face passes |
| `PLATE_MIN_CONF` | `0.55` | OCR confidence floor for pushing ANPR events |
| `FACE_MATCH_THRESHOLD` | `0.45` | ArcFace cosine similarity threshold |

## Sizing & rate

At `SAMPLE_FPS=1` per camera, a single CPU core handles ~3 cameras; each
ingested event is < 1 KB of metadata — the "99% bandwidth reduction vs raw
video" claim from plan §1. GPU accelerates 50+ cameras on one node.

## Security

- The worker authenticates to the ingest API with `X-API-Key`
  (`INGEST_API_KEY`). The key lives only in the worker's environment and the
  Render service config — never committed (`.env` is gitignored).
- Video frames are processed in memory and never persisted.
