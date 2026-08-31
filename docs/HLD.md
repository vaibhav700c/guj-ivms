# Gujarat IVMS — High-Level Design

> Companion to `plan.md`. Describes the implemented system end-to-end.

## 1. Architectural Model

**Hybrid — Model 1 (Registry+GIS) + Model 2 (Unified Viewing) + Model 3 (Federation Ingest) + selective Model 4 (centralized analytics/alerts).**

```
┌──────────────────────┐     ┌─────────────────────────────┐     ┌────────────────────────────────────┐
│   CAMERA SOURCES     │     │  EDGE / REGIONAL ANALYTICS  │     │        CENTRAL PLATFORM           │
│  Dept VMS · RTSP ·   │ ──► │   ANPR · Detection · Tracks │ ──► │  FastAPI: correlation · GIS ·     │
│  Sentinel grid ·     │     │   YOLO/ByteTrack/PaddleOCR  │     │  search · dashboards · WS push    │
│  ONVIF (adapters)    │     │   (simulator in demo)       │     │  PostgreSQL + Redis · MediaMTX   │
└──────────────────────┘     └─────────────────────────────┘     └────────────────────────────────────┘
        raw video stays local                 metadata + alerts only (≈99% bandwidth reduction)
```

## 2. Components

| Component | Tech | Responsibility |
|---|---|---|
| API Gateway | FastAPI + uvicorn | REST `/api/v1/*`, JWT+RBAC, CORS |
| Data layer | SQLAlchemy 2 · SQLite (dev) / PostgreSQL (prod) | Departments, cameras, watchlist, ANPR/detection events, alerts, users, camera health log, VAHAN-like registry |
| Alert Engine | `app/alert_engine.py` | Watchlist correlation: exact + OCR-fuzzy plate match, face-name similarity → Alert rows + WS push |
| Event bus | in-process asyncio + optional Redis pub/sub | `alerts:new`, `analytics:new` channels; cross-replica fan-out |
| Realtime | WebSockets `/ws/alerts`, `/ws/analytics` | Control-room live feeds |
| Federation ingest | `POST /ingest/anpr|detection` + `X-API-Key` | Model 3 adapter contract |
| Simulator | `app/simulator.py` | Emulates edge nodes; generates ANPR, detections, faces, health samples |
| UI | React + Vite + TS + Tailwind + Leaflet + Recharts | Control-room SPA |
| Streaming | MediaMTX (docker-compose) | RTSP → WebRTC/HLS conversion (production-full-stack) |
| Object store | MinIO (docker-compose) | Snapshot refs (URLs stored in DB) |

## 3. Key Data Flows

1. **ANPR event ingest** → stored → evaluated vs active watchlist → `Alert` row → WS push to open control rooms → visible on Dashboard/Alerts.
2. **Face recognition (Tier A)** → detections with embedding stub → person watchlist correlation → `watchlist_person` alerts.
3. **Vehicle journey** → plate-normalized search across all ANPR events → sighting timeline → haversine legs (distance, elapsed, speed) → GIS polyline replay.
4. **Camera health** → heartbeat + `camera_health_log` time series every cycle.

## 4. API Surface (v1)

| Group | Endpoints |
|---|---|
| auth | `POST /auth/login`, `GET /auth/me` |
| cameras | `GET/POST /cameras`, `GET /cameras/stats`, `GET /geo/nearby`, `GET /geo/coverage`, `GET /gap-analysis`, `POST /bulk`, `PATCH/DELETE /cameras/{id}`, `GET /cameras/{id}/health-log`, `GET /departments/list` |
| feeds | `GET /feeds/status`, `GET /feeds/{id}/url` |
| departments | `GET/POST /departments`, `GET /departments/{id}` |
| watchlist | `GET/POST /watchlist`, `PATCH/DELETE /watchlist/{id}` |
| alerts | `GET /alerts`, `GET /alerts/stats`, `PATCH /alerts/{id}/status` |
| analytics | `GET /overview`, `GET /events/timeline`, `GET /detections/by-type`, `GET /tiers/coverage`, `GET /anpr`, `GET /anpr/search`, `GET /faces`, `GET /traffic`, `GET /events` |
| vehicles | `GET /search/{plate}`, `GET /journey/{plate}`, `GET /last-seen/{plate}`, `GET /registry/{plate}`, `GET /recent`, `GET /traffic/by-hour`, `GET /traffic/by-camera` |
| reports | `GET /reports/{alerts,anpr,cameras}.csv` |
| ingest | `POST /ingest/anpr`, `POST /ingest/detection` (X-API-Key) |
| system | `GET /health`, `GET /config`, `GET /adapters` |
| users | `GET/POST /users`, `PATCH /users/{id}` (admin) |
| simulator | `GET /status`, `POST /start`, `POST /stop` |
| ws | `/ws/alerts`, `/ws/analytics` |

## 5. Security

- PBKDF2-SHA256 (390k iterations) password hashing; JWT HS256; RBAC (admin/operator/analyst/viewer).
- `REQUIRE_AUTH=true` in strict deployments; ingest keyed via `X-API-Key`.
- Raw video never transits the API (metadata + snapshot refs only).

## 6. Scaling Path (→ 80,000 cameras)

- Horizontal API replicas + Redis pub/sub fan-out (configured via `REDIS_URL`).
- Regional analytics at the edge (Tier A/B/C) egressing metadata only.
- Partitioned/time-series event tables (hypertable path in docker-compose Postgres).
- CDN-cached static frontend; MediaMTX relays per regional cluster.