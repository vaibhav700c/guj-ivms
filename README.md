# Gujarat IVMS — Integrated Video Management & Analytics Platform

> Gujarat Police hackathon build · **Hybrid architecture (Model 1 + 2 + 3 + selective 4)** · 100% open-source · zero vendor lock-in

A working end-to-end implementation of the plan in [`../plan.md`](../plan.md):

```
Camera → Edge/Regional Analytics Node → Metadata + Alerts → Central Platform
        (ANPR, detection, tracking)    (NOT raw video)     (correlation, search, GIS, dashboards)
```

Raw video stays with departmental systems. Only structured metadata flows to the center — the guiding principle: **"analytics at the edge, correlation at the center."**

## What's implemented

| Layer | Plan model | Where |
|---|---|---|
| Camera Registry + GIS (50 seeded Gujarat cameras with real coordinates) | Model 1 | `backend/app/routes/cameras.py`, frontend **Camera Registry** + **GIS Map** pages |
| Unified viewing grid (2×2 / 3×3 / 4×4, OSD overlays, MediaMTX-ready) | Model 2 | frontend **Live View** page |
| Federation ingest API for edge/regional nodes (adapter contract + API-key) | Model 3 | `POST /api/v1/ingest/anpr`, `POST /api/v1/ingest/detection` |
| Central analytics: ANPR events, detections, tiering (A/B/C), VAHAN-like registry | Model 4 | `backend/app/routes/{analytics,vehicles}.py` |
| Watchlist correlation engine → real-time WebSocket alerts | Model 4 | `backend/app/alert_engine.py`, **Live Alerts** page (ack/resolve workflow + sound) |
| Face-recognition correlation for wanted/missing persons (Tier A) | plan §6 | `backend/app/alert_engine.py` → `watchlist_person` alerts |
| Vehicle search & journey reconstruction (haversine legs, implied speeds, map replay, probable OCR matches) | plan §7 / §20.2 | **Vehicle Search** page |
| Camera health monitoring (time-series health log, feeds/status) | plan §9.1 / §13 | `GET /cameras/{id}/health-log`, `/feeds/status` |
| GIS coverage + gap analysis report | plan §9.2 / §13 | `GET /cameras/geo/coverage`, `/cameras/gap-analysis` |
| Federation connector registry | plan §11.2 | `GET /system/adapters` |
| Live snapshot capture (`GET /feeds/{id}/snapshot`, ffmpeg over live HLS) | plan §13 | `backend/app/routes/feeds.py` |
| Watchlist bulk import (JSON/CSV) + PDF report exports | plan §13 / §20 | `POST /watchlist/bulk-import`, `GET /reports/{kind}.pdf` |
| Per-camera analytics WebSocket (`/ws/analytics/{camera_id}`) | plan §13 | `backend/app/routes/ws.py` |
| Backend test suite (19 e2e tests: ingest→alert→resolve, journey, PDF, RBAC) | robustness | `backend/tests/` |
| Demo simulator (edge-node emulation) — makes the deployed product live-demoable | plan §20 | `backend/app/simulator.py` |
| JWT + RBAC auth, PBKDF2 password hashing, user management | plan §17 | `backend/app/security.py`, `routes/users.py` |

## Deliverables (plan §21)

- **HLD** — [docs/HLD.md](docs/HLD.md)
- **Solution presentation (20-slide PDF)** — [docs/PRESENTATION.pdf](docs/PRESENTATION.pdf) (regenerate: `python docs/generate_presentation.py`)
- **Demo script (2–3 min, plan §20.2 test scenario)** — [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md)
- **Deployment guide** — [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)
- **API reference** — [docs/API.md](docs/API.md) · live Swagger at `/docs`
- **Security architecture** — [docs/SECURITY.md](docs/SECURITY.md)
- **This repository** with full code + docker-compose + deploy configs

## Quick start (zero-config dev)

```bash
# Backend (SQLite fallback — no Postgres needed)
cd backend
python -m venv .venv && .venv/bin/pip install -r requirements.txt pytest
.venv/bin/uvicorn app.main:app --port 8000
# Seeded automatically: 30 Sentinel Grid cameras, watchlist, VAHAN records, users
# Demo simulator starts automatically and generates live events + alerts

# Run the test suite (isolated SQLite DB, deterministic — simulator disabled)
.venv/bin/python -m pytest tests/ -v

# Frontend
cd frontend
npm install && npm run dev        # http://localhost:5173
```

Login: `admin / admin123` (or any visit — demo mode auto-authenticates when `REQUIRE_AUTH=false`).

## Full stack (Postgres + PostGIS + Redis + MinIO + MediaMTX)

```bash
docker compose up --build
```

## Cloud deployment (already wired)

**🔴 Live URLs**

| Component | URL |
|---|---|
| Control Room UI (Vercel) | **https://guj-ivms.vercel.app** |
| Backend API (Render) | **https://guj-ivms-api.onrender.com** |
| Swagger docs | https://guj-ivms-api.onrender.com/docs |
| WebSocket live alerts | wss://guj-ivms-api.onrender.com/ws/alerts |

Deployed via Render (Docker backend + managed PostgreSQL, `render.yaml` Blueprint
spec in repo) and Vercel (`frontend/vercel.json`, Vite). First boot auto-seeded
50 cameras, watchlist, VAHAN records and users into Postgres, and the demo
simulator is generating live events/alerts.

## API surface (v1)

```
POST /api/v1/auth/login                 GET  /api/v1/auth/me
GET/POST/PATCH/DELETE /api/v1/cameras   GET  /api/v1/cameras/stats
GET/POST/PATCH/DELETE /api/v1/watchlist
GET  /api/v1/alerts                     PATCH /api/v1/alerts/{id}/status
GET  /api/v1/analytics/overview         GET  /api/v1/analytics/events/timeline
GET  /api/v1/vehicles/search/{plate}    GET  /api/v1/vehicles/registry/{plate}
GET  /api/v1/vehicles/traffic/*         GET  /api/v1/reports/*.csv
POST /api/v1/ingest/anpr                POST /api/v1/ingest/detection
GET  /api/v1/simulator/status           POST /api/v1/simulator/{start,stop}
WS   /ws/alerts                         GET  /health
```

Interactive docs: `/docs` (Swagger UI).

## Production hardening checklist

- Set `REQUIRE_AUTH=true` + strong `SECRET_KEY` (Render `generateValue`).
- Set `SIMULATOR_AUTO_START=false` once real ingest nodes are connected; keep `INGEST_API_KEY`.
- Redis (`REDIS_URL`) enables cross-replica WebSocket fan-out for scaling beyond one instance.
- Raw video never transits this API — object store (MinIO/S3) references only (`snapshot_ref`).

## Tech stack (all free / open-source)

FastAPI · SQLAlchemy 2 · PostgreSQL (+PostGIS/TimescaleDB in full stack) · Redis · SQLite fallback · React 18 + Vite + TypeScript · Tailwind CSS · Leaflet + OpenStreetMap · Recharts · WebSocket · Docker Compose · MediaMTX · MinIO.

See [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) for step-by-step deploy instructions.
