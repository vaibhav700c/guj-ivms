# API Reference — Gujarat IVMS

Base URL (production): `https://guj-ivms-api.onrender.com`
Interactive docs: [`/docs`](https://guj-ivms-api.onrender.com/docs) (Swagger UI) · `/redoc`

All business endpoints are versioned under `/api/v1`. Authentication uses JWT
Bearer tokens (`Authorization: Bearer <token>`) obtained from
`POST /api/v1/auth/login` (OAuth2 form: `username`, `password`).
When the backend runs with `REQUIRE_AUTH=false` (demo mode), endpoints are open
and `/auth/me` reports `auth_mode: "disabled"`.

## System

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Liveness probe |
| GET | `/api/v1/system/health` | DB + simulator status |
| GET | `/api/v1/system/config` | Non-secret runtime config |
| GET | `/api/v1/system/adapters` | Federation connector registry (plan §11.2) |
| POST | `/api/v1/system/reseed` | Re-seed demo data |

## Auth (plan §17)

| Method | Path | Description |
|---|---|---|
| POST | `/api/v1/auth/login` | OAuth2 form login → JWT + user |
| GET | `/api/v1/auth/me` | Current user (demo user when auth disabled) |

## Camera Registry + GIS (plan §9 / §13)

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/cameras` | List — filters: `department_id, district, city, status, tier, limit, offset` |
| POST | `/api/v1/cameras` | Register one camera |
| GET | `/api/v1/cameras/stats` | Counts by status / tier / city |
| GET | `/api/v1/cameras/geo/nearby?lat&lng&radius_km` | Cameras near a point |
| GET | `/api/v1/cameras/geo/coverage` | Coverage heat data per camera |
| GET | `/api/v1/cameras/gap-analysis` | Uncovered districts report |
| POST | `/api/v1/cameras/bulk` | Bulk import (JSON array) |
| GET | `/api/v1/cameras/{id}` | Camera detail |
| PUT / PATCH | `/api/v1/cameras/{id}` | Update camera metadata |
| DELETE | `/api/v1/cameras/{id}` | Remove camera |
| GET | `/api/v1/cameras/{id}/health-log` | Time-series health samples (plan §9.1) |

## Live Feeds (plan §10 / §13)

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/feeds/status` | All-feed health summary |
| GET | `/api/v1/feeds/{camera_id}/url` | HLS / WebRTC / RTSP playback URLs |
| GET | `/api/v1/feeds/{camera_id}/snapshot` | Current frame JPEG (ffmpeg over live HLS; 8s cache) |

## Sentinel Grid proxy (real stream infrastructure)

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/sentinel/catalogue` | Live camera list merged with registry |
| GET | `/api/v1/sentinel/hls/{cam}/index.m3u8` | Authenticated HLS playlist (rewritten) |
| GET | `/api/v1/sentinel/hls/{cam}/enc.key` | AES-128 key proxy |
| GET | `/api/v1/sentinel/hls/{cam}/{segment}` | Media segment proxy |
| GET | `/api/v1/sentinel/stream-info/{cam}` | All endpoints for one camera |

## Analytics (plan §4 / §13)

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/analytics/overview` | KPI totals |
## Watchlist (plan §8 / §13)

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/watchlist` | List — filters: `category, subject_type, severity, active` |
| POST | `/api/v1/watchlist` | Add entry |
| PATCH | `/api/v1/watchlist/{id}` | Update entry |
| DELETE | `/api/v1/watchlist/{id}` | Remove entry |
| POST | `/api/v1/watchlist/bulk-import` | Bulk import — JSON `{"items":[...]}` / array or CSV (`text/csv` body, header row `category,subject_type,identifier,severity,description,fir_number,police_station`). Deduplicates; returns created/skipped breakdown. |

## Alerts (plan §8 / §13)

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/alerts` | List — filters: `status, severity, alert_type, camera_id, limit, offset` |
| GET | `/api/v1/alerts/stats` | Counts by status / severity / type |
| PUT | `/api/v1/alerts/{id}/acknowledge` | Acknowledge alert |
| PUT | `/api/v1/alerts/{id}/resolve` | Resolve alert |
| PATCH | `/api/v1/alerts/{id}/status` | Generic status update (`acknowledged` / `resolved` / `false_positive`) |

## Federation ingest — Model 3 (edge/regional nodes push metadata)

`X-API-Key` header is checked against `INGEST_API_KEY` when that env var is set.

| Method | Path | Description |
|---|---|---|
| POST | `/api/v1/ingest/anpr` | `{camera_id, plate_text, confidence, vehicle_type?, direction?, snapshot_ref?, timestamp?}` → watchlist correlation + alert |
| POST | `/api/v1/ingest/detection` | `{camera_id, event_type, confidence, bbox?, metadata?}` |

## Reports (plan §20 — CSV/PDF export)

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/reports/alerts.csv` / `.pdf` | Alert report |
| GET | `/api/v1/reports/anpr.csv` / `.pdf` | ANPR detection report |
| GET | `/api/v1/reports/cameras.csv` / `.pdf` | Camera registry report |

## Simulator (demo edge-node emulation)

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/simulator/status` | Running state + counters |
| POST | `/api/v1/simulator/start` / `stop` | Control event generation |

## WebSocket (plan §13)

| Endpoint | Description |
|---|---|
| `WS /ws/alerts` | Real-time alert push — payload `{type:"alert", payload:{...}}`; client may send `ping` |
| `WS /ws/analytics` | Live detection overlay stream — all cameras |
| `WS /ws/analytics/{camera_id}` | Live detection overlay stream — one camera only |

## Departments / Users

| Method | Path | Description |
|---|---|---|
| GET/POST | `/api/v1/departments` · GET `/{id}` | Department registry |
| GET/POST | `/api/v1/users` · PATCH `/{id}` | User management (RBAC roles: `admin`, `operator`, `analyst`, `viewer`) |
| GET | `/api/v1/cameras/departments/list` | Department options for camera forms |

| GET | `/api/v1/analytics/anpr` | ANPR events — filters: `plate, camera_id, hours, limit` |
| GET | `/api/v1/analytics/anpr/search?plate=` | Plate search (normalized) |
| GET | `/api/v1/analytics/faces` | Face detection events (Tier A) |
| GET | `/api/v1/analytics/traffic` | Traffic density per camera |
| GET | `/api/v1/analytics/events` | Generic detection event stream |
| GET | `/api/v1/analytics/events/timeline?hours=` | Bucketed event timeline |
| GET | `/api/v1/analytics/detections/by-type` | Counts by event type |
| GET | `/api/v1/analytics/tiers/coverage` | Tier A/B/C camera distribution |

## Vehicles (plan §7 / §13 / §20.2)

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/vehicles` | VAHAN-like registry list |
| GET | `/api/v1/vehicles/search/{plate}` | Full timeline + journey legs + probable OCR matches |
| GET | `/api/v1/vehicles/journey/{plate}` | Route reconstruction (waypoints, distance, cities) |
| GET | `/api/v1/vehicles/last-seen/{plate}` | Most recent sighting |
| GET | `/api/v1/vehicles/registry/{plate}` | Registry record lookup |
| GET | `/api/v1/vehicles/recent` | Latest ANPR sightings |
| GET | `/api/v1/vehicles/traffic/by-hour` | Hourly histogram |
| GET | `/api/v1/vehicles/traffic/by-camera` | Busiest cameras |
