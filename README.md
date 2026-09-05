# Gujarat IVMS — Integrated Video Management & Analytics Platform

> Gujarat Police hackathon build · hybrid architecture (Model 1 + 2 + 3 + selective 4) · 100% open-source

```mermaid
flowchart LR
    CAM[("Sentinel Grid<br/>30 real CCTV cameras")]
    EDGE["Edge Analytics<br/>YOLOv8 · ByteTrack · plate OCR · ArcFace<br/>(your own machine — never Render)"]
    API["Central Platform — FastAPI on Render<br/>correlation · GIS · search · dashboards"]
    UI["Control Room — React on Vercel"]

    CAM -->|RTSP| EDGE
    EDGE -->|"metadata + alerts only<br/>(never raw video)"| API
    API -->|REST + WebSocket| UI

    style CAM fill:#0d1a2e,stroke:#f97316,color:#e2e8f0
    style EDGE fill:#0d1a2e,stroke:#f97316,color:#e2e8f0
    style API fill:#0d1a2e,stroke:#06b6d4,color:#e2e8f0
    style UI fill:#0d1a2e,stroke:#10b981,color:#e2e8f0
```

Raw video never leaves the edge. Only structured metadata — plate strings, bounding
boxes, confidences, face embeddings — reaches the central platform. That's what makes
an 80,000-camera target bandwidth-plausible, and it's the one rule every code path here
follows: never ship frames to the backend. Full component, data-flow and deployment
diagrams: [`docs/HLD.md`](docs/HLD.md).

The full spec is `plan.md` at the repo root — deliberately gitignored, along with
`integration_camera.txt` (live camera-grid credentials), because this repository is
public. If either is missing from your checkout, ask for it rather than guessing; this
README and `docs/` describe what's actually built, which is the reliable source for
current behavior.

## Real data only — how this is actually enforced

Every event this platform stores carries a `source` field: `"edge_worker"` for a
genuine detection from the real CV pipeline, `"simulator"` for the bundled demo
generator. This isn't a cosmetic label — it's enforced at write time (the ingest API
hardcodes it server-side; a POST body can never spoof it), it's filterable on every
list endpoint (`?source=edge_worker`), and the frontend's **"Real detections only"**
toggle in the top bar — **on by default** — hides everything else. A simulated row that
does slip through a filtered view still can't pass as real: it carries a visible
`SIMULATED` badge everywhere it appears.

The demo simulator itself defaults to **off** (`SIMULATOR_AUTO_START=false`), and a
second guard refuses to auto-start it at all when `ENVIRONMENT=production`, even if
that variable drifts back to `true` on the hosting platform — this was a real
production incident during development (see `git log --grep=simulator`), not a
hypothetical.

This matters because it's the actual failure mode this project fought hardest: a
hackathon demo is trivial to fake with a random-data generator, and a fake result
that's indistinguishable from a real one is worse than an honest "not implemented."
Nothing in this README claims a capability that wasn't independently verified against
the real Sentinel Grid feeds.

## What's real, and what's honestly still hard

**Genuinely working, verified against live camera footage, not simulated:**

- Live HLS video from 30 real Sentinel Grid cameras (AES-128 decrypted client-side)
- Real-time YOLOv8 person/vehicle/face detection, with the actual bounding box
  drawn by OpenCV directly into the evidence JPEG — not a CSS overlay computed
  after the fact, the box is baked into the pixels the model actually saw
- Real license-plate OCR with Indian-format validation (RTO district table, 4-digit
  tail, no ambiguous I/O series letters) and multi-read voting before anything is
  accepted — corroborated example: `GJ11T5967` on cam06 (Timbavadi Gate, Junagadh),
  a school bus lettered "Amrut Institute Junagadh" — GJ-11 genuinely is the
  Junagadh RTO code
- Real ArcFace face embeddings + cosine-similarity re-identification across cameras
- Cross-camera vehicle re-identification via HSV appearance histograms, for the
  cameras where plate OCR is confirmed physically impossible (see below)
- GIS coordinates and journey reconstruction driven entirely by real detection
  events joined to the real camera registry — no fabricated routes or coordinates
- Per-camera CV capability verification: an automated, isolated run of the real
  pipeline against one camera, recording exactly what it found (frame count,
  detections by type, plates read, a real representative evidence photo) —
  see **Camera Registry** → any camera → "Verified CV Capability"

**Measured, not assumed, and honestly reported:**

- Plate OCR accuracy is fundamentally limited by camera resolution and lighting on
  most of the 30 feeds. 11 of 30 cameras were reviewed frame-by-frame by a human
  operator and confirmed physically incapable of a legible plate read (headlight
  glare, distance, motion blur, B&W night mode) — those cameras skip ANPR entirely
  rather than let an OCR model hallucinate on noise it can't resolve. The 9
  cameras confirmed plate-legible do produce real, corroborated reads; the rest of
  the grid falls back to appearance-based vehicle correlation.
- Running many camera pipelines concurrently on one machine measurably degrades
  each one's real frame rate — a 30-camera parallel sweep dropped effective
  throughput to 5-14× below target on a single laptop, which is a genuine hardware
  ceiling, not a bug, and is exactly why the edge worker is designed to scale
  horizontally across nodes rather than vertically on one box.
- Face re-identification requires the same enrolled person to physically re-appear
  in frame; this is inherently probabilistic on wide-angle traffic cameras and
  isn't claimed to work on demand.

## Quick start (zero-config dev)

```bash
# Backend (SQLite fallback — no Postgres needed)
cd backend
python -m venv .venv && .venv/bin/pip install -r requirements.txt pytest
.venv/bin/uvicorn app.main:app --port 8000
# Auto-seeds: 30 real Sentinel Grid cameras (real coordinates), watchlist, VAHAN
# records, users. Simulator is OFF by default — the dashboard starts empty until
# a real edge worker ingests events, or you deliberately POST /api/v1/simulator/start.

.venv/bin/python -m pytest tests/ -v   # 24 tests, isolated SQLite, simulator disabled

# Frontend
cd frontend
npm install && npm run dev        # http://localhost:5173
npx tsc --noEmit && npm run build  # both must pass before committing
```

Login: `admin` / `admin123` (or just visit — `REQUIRE_AUTH=false` auto-authenticates).

**First load of any route is slow in dev mode** (a few seconds) — that's Vite compiling
that route's modules on demand, a one-time cost per file per dev-server session, not a
network or backend problem. `npm run build && npm run preview` skips it entirely
(confirmed under 2s cold in both modes) and is what's actually deployed to Vercel.

## The real CV pipeline

```bash
cd analytics
python -m venv .venv && .venv/bin/pip install -r requirements.txt   # pulls torch, insightface (~330MB first run)
export SENTINEL_EMAIL=... SENTINEL_PASSWORD=...   # both required — see Traps below

# Sanity check the video source with zero ML involved
.venv/bin/python worker.py test-rtsp --camera 6 --out /tmp/f.jpg

# The always-on edge worker (posts to a running backend)
timeout 150 .venv/bin/python worker.py run        # ALWAYS bound it; loops forever

# The Investigate page's on-demand bridge — upload a photo or enter a plate,
# pick cameras, watch real detections happen (needs the backend running)
.venv/bin/uvicorn control_server:app --port 8800

# Verify one camera's real capability in isolation, no CPU contention with
# anything else — records a CameraCapabilityRun the UI can show
.venv/bin/python run_capability_audit.py --cameras 4,6,12

# Capture against many cameras with NEITHER the backend nor control_server
# running — durable local SQLite instead, true concurrent capture safe since
# there's no live UI to protect from CPU contention. Replay it in afterward:
.venv/bin/python offline_capture.py --cameras all --duration 300 --parallel
.venv/bin/python replay_offline_capture.py   # once the backend is back up
```

See [`docs/ANALYTICS.md`](docs/ANALYTICS.md) for the model stack, degradation
behavior, and per-camera capability config.

## Investigate — wanted-person photo search & live plate watch

The real CV stack (YOLOv8 + InsightFace ArcFace + plate OCR, ~2GB RAM) never runs on
Render's 512MB free tier — it runs on your own machine, driving the same
`analytics/` worker code the always-on edge pipeline uses. Open the **Investigate**
page (works against the deployed site too — `localhost:8800` fetches from an HTTPS
page aren't blocked as mixed content since `localhost` is a spec'd trustworthy origin),
upload a reference photo or enter a plate, pick real cameras, and start monitoring.
The page shows the actual live camera footage plus a live-updating strip of real
annotated detection frames while it runs — not a status line, actual video and actual
evidence images. Matches raise real alerts (camera, timestamp, confidence, the real
detection frame) on **Live Alerts** and the **GIS Map**.

## Full stack (Postgres + PostGIS + Redis + MinIO + MediaMTX)

```bash
docker compose up --build
```

## Cloud deployment (already wired)

| Component | URL |
|---|---|
| Control Room UI (Vercel) | **https://guj-ivms.vercel.app** |
| Backend API (Render) | **https://guj-ivms-api.onrender.com** |
| Swagger docs | https://guj-ivms-api.onrender.com/docs |
| WebSocket live alerts | wss://guj-ivms-api.onrender.com/ws/alerts |

Both platforms auto-deploy on push to `master`. First boot auto-seeds the 30 real
Sentinel Grid cameras, watchlist, VAHAN records, and users.

> **Deploying this yourself:** apply `render.yaml` as a Render **Blueprint**, not a
> hand-created service — otherwise none of its environment variables reach the
> container and the API silently falls back to an ephemeral SQLite file wiped on every
> restart. `SENTINEL_EMAIL` **and** `SENTINEL_PASSWORD` are both required — the grid's
> sign-in form rejects a password-only POST with an HTTP 200 and no cookie, so a naive
> status check reads that as success. Setting env vars on Render does **not** itself
> trigger a redeploy.

## API surface (v1)

```
POST /api/v1/auth/login                 GET  /api/v1/auth/me
GET/POST/PATCH/DELETE /api/v1/cameras   GET  /api/v1/cameras/{id}/capability-runs
GET/POST/PATCH/DELETE /api/v1/watchlist
GET  /api/v1/alerts                     PATCH /api/v1/alerts/{id}/status
GET  /api/v1/analytics/overview         GET  /api/v1/analytics/events?source=edge_worker
GET  /api/v1/vehicles/search/{plate}    GET  /api/v1/vehicles/journey/{plate}
GET  /api/v1/vehicles/traffic/*         GET  /api/v1/reports/*.csv
POST /api/v1/ingest/anpr                POST /api/v1/ingest/detection
GET  /api/v1/simulator/status           POST /api/v1/simulator/{start,stop}
WS   /ws/alerts                         GET  /health
```

Interactive docs: `/docs` (Swagger UI). Full reference: [`docs/API.md`](docs/API.md).

## Traps that have already cost real debugging time

- **`SENTINEL_EMAIL` and `SENTINEL_PASSWORD` are both required**, everywhere the
  Sentinel Grid is touched (HLS proxy, RTSP worker, control_server). Missing either
  silently 503s every live-video/snapshot/detection path.
- **RTSP uses HTTP Basic auth** — percent-encode credentials into the URL userinfo.
- **The plate OCR model is single-channel** — a 3-channel BGR crop fails ONNX shape
  validation on the channel axis and silently disables ANPR.
- **The upstream CDN is Cloudflare-fronted and rate-limits by source IP.** Do not
  load-test it. The backend proxies every viewer through one address; playlists and
  segments are cached, concurrent identical fetches are coalesced, and a background
  warmer keeps the default live-grid cameras pre-fetched so a normal page load never
  pays the upstream's own ~4-25 KB/s cold-fetch cost.
- **A threshold expressed in raw sample count silently changes meaning if the sample
  rate changes** — caught live when raising the CV worker's FPS cut a static-background
  filter's effective grace period in half. Anything gating on "N occurrences in a
  window" should gate on real elapsed time instead.
- **Python's `threading.Thread` reserves a private `_stop()` method** — naming your own
  instance attribute `self._stop` silently shadows it and only crashes inside
  `Thread.join()`, which may not be called on every code path that uses the thread.
- Full list, including Render/Postgres-specific traps: see `CLAUDE.md`.

## Tech stack (all free / open-source)

FastAPI · SQLAlchemy 2 · PostgreSQL (+PostGIS/TimescaleDB in the full stack) · Redis ·
SQLite fallback · React 18 + Vite + TypeScript · Tailwind CSS · Leaflet + OpenStreetMap ·
Recharts · WebSocket · YOLOv8 (ultralytics) · ByteTrack (supervision) · fast-plate-ocr ·
InsightFace (buffalo_l / ArcFace) · Docker Compose · MediaMTX · MinIO.

## Deliverables

- **HLD** — [docs/HLD.md](docs/HLD.md)
- **Analytics pipeline** — [docs/ANALYTICS.md](docs/ANALYTICS.md)
- **Demo script** — [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md)
- **Deployment guide** — [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)
- **API reference** — [docs/API.md](docs/API.md) · live Swagger at `/docs`
- **Security architecture** — [docs/SECURITY.md](docs/SECURITY.md)
- **Solution presentation** — [docs/PRESENTATION.pdf](docs/PRESENTATION.pdf)
  (regenerate: `python docs/generate_presentation.py`)
