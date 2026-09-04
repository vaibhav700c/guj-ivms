# Orientation for Claude Code sessions

Read this before changing anything. It records the things that are **not** obvious
from the code and that have already cost real debugging time.

## What this is

Gujarat IVMS — an Integrated Video Management & Analytics Platform built for a
Gujarat Police hackathon. CCTV registry + GIS, a unified live video wall, a
federation ingest API, and central watchlist correlation that raises alerts.

The whole design follows one principle: **"analytics at the edge, correlation at
the center."** Only structured metadata (plates, detections, alerts) travels to
the central platform — never raw video. That is what makes the stated 80,000
camera target plausible, and it is why you should never introduce a code path
that ships frames to the backend.

The full specification is `plan.md` at the repo root. **It is deliberately
gitignored** (see "Files kept out of git" below), so if it is missing from your
checkout, ask the user for it rather than guessing at requirements. `README.md`
and `docs/HLD.md` are committed and describe what is actually built, which is
the more reliable guide to current reality.

## Layout

```
backend/     FastAPI + SQLAlchemy 2. The central platform. Deployed to Render.
frontend/    React 18 + Vite + TS + Tailwind + Leaflet. Deployed to Vercel.
analytics/   The real edge ML worker (YOLOv8 + ByteTrack + plate OCR). Runs
             locally/on-prem, NEVER on Render — it needs ~2GB RAM.
docs/        HLD, API reference, deployment, security, demo script.
db/          init.sql — vestigial. Models use create_all; this file is unused.
config/      mediamtx.yml — only for the full local docker-compose stack.
```

## Two event sources — know which one you are looking at

1. **`backend/app/simulator.py`** — an in-process demo generator, on by default
   (`SIMULATOR_AUTO_START`). It fabricates ANPR/detection/health events every 2s
   so the dashboard, alerts and journey replay are demonstrable without cameras.
   Disabled automatically during tests.
2. **`analytics/worker.py`** — the genuine ML pipeline against real cameras. It
   POSTs to `/api/v1/ingest/{anpr,detection}` like any third-party edge node.

Both feed the same correlation engine. When something looks "too good", check
which source produced it.

## Local setup

**Python 3.10+ is required** — the codebase uses PEP 604 (`X | None`) syntax and
will not even import on 3.9.

```bash
# Backend (SQLite fallback, zero config)
cd backend && python -m venv .venv
.venv/bin/pip install -r requirements.txt pytest
.venv/bin/python -m pytest tests/ -q          # 24 tests, all should pass
.venv/bin/uvicorn app.main:app --port 8000

# Frontend
cd frontend && npm install && npm run dev     # http://localhost:5173
npx tsc --noEmit && npm run build             # both must pass before committing

# Edge ML worker (optional, heavy — pulls torch)
cd analytics && python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python worker.py test-rtsp --camera 6 --out /tmp/f.jpg   # sanity check
timeout 150 .venv/bin/python worker.py run    # ALWAYS bound it; it loops forever
```

Login: `admin` / `admin123`. When `REQUIRE_AUTH=false` the UI auto-authenticates.

## Traps that have already bitten

- **Apply `render.yaml` as a Render *Blueprint*.** Creating the service by hand
  means none of its env vars exist, and the app silently falls back to an
  ephemeral SQLite file that is wiped on every restart. This actually happened.
- **`SENTINEL_EMAIL` *and* `SENTINEL_PASSWORD` are both required.** The camera
  grid's sign-in form posts both; sending only the password re-renders the login
  page as HTTP 200 with no cookie, so naive status checks read it as success.
  Without both, every live-video and snapshot endpoint 502s.
- **RTSP uses HTTP Basic auth** (realm `ipcam`). Credentials must be
  percent-encoded into the URL userinfo — the `@` in the email becomes `%40`, or
  the URL resolves to the wrong host.
- **The plate OCR model is single-channel.** Hand it a 3-channel BGR crop and
  ONNX rejects it on the channel axis, silently disabling ANPR. Convert to
  grayscale first.
- **Iterating `supervision.Detections` yields plain tuples**, not per-detection
  objects. Index the parallel arrays (`.class_id[i]`, `.xyxy[i]`) instead.
- **`av>=18` requires Python 3.11+.** On 3.10 pip aborts the entire dependency
  resolve while still exiting 0, so nothing installs. The pin is `>=14`.
- **The CDN is behind Cloudflare, which rate-limits by source IP.** The backend
  proxies every viewer through one address, so bursts get 403s for everybody.
  Playlists/segments/keys are cached and identical concurrent fetches are
  coalesced; the video wall staggers tile startup. **Do not load-test the CDN** —
  it is a third-party service and it will throttle the deployment.
- **A new Render Postgres blocks external connections by default** (empty
  `ipAllowList`), so connecting from a laptop fails regardless of credentials.
  Use the internal connection string; the only meaningful test is a deploy.
- **Render hands out `postgres://` URLs, which SQLAlchemy 2 rejects.**
  `backend/app/db.py` normalises the scheme — don't remove that.

## Security model

RBAC (`Permission` enum + `ROLE_PERMISSIONS` in `backend/app/security.py`) and the
audit trail are implemented, but **every gate is a deliberate no-op while
`REQUIRE_AUTH=false`**, which is how the public demo stays frictionless. Setting
`REQUIRE_AUTH=true` activates enforcement with no code change. If you add a
mutating endpoint, gate it with `require_permission(...)` and write an audit
entry — follow the existing routes.

Free tier reality: 512MB RAM and 0.1 CPU. Never load a whole table, always cap
`limit` query params, and eager-load relationships or you will N+1 the database.

## Files kept out of git

`plan.md` and `integration_camera.txt` are gitignored. `integration_camera.txt`
carries live camera-grid credentials, and this repository is **public** — never
commit either, and never paste their contents into code, comments or commit
messages. All secrets belong in environment variables: `SENTINEL_EMAIL`,
`SENTINEL_PASSWORD`, `INGEST_API_KEY`, `SECRET_KEY`, `DATABASE_URL`.

## Deploying

Both platforms **auto-deploy on push to `master`** — Render for the backend,
Vercel for the frontend. So verify against the live URLs a minute or two after
pushing. Setting env vars on Render does *not* itself trigger a redeploy.

## Known limitation: live ANPR

Live plate reading does **not** work on the current night camera feeds, and this
was measured rather than assumed. Plate crops come through at 35-64px wide; seven
preprocessing variants (including the plan's own §5.3 and §5.4 recipes) each
returned zero format-valid plates, and each read the same crop differently —
the OCR hallucinating on noise. The information is not present at that
resolution, so no preprocessing recovers it.

The pipeline itself is proven correct end to end and has landed genuine plates.
`plate_min_width_px` (default 60, per plan §4) now drops undersized crops and
counts them as `rejected_too_small`, so the failure is visible and points at
camera placement instead of producing fabricated plates. Re-measure in daylight
before concluding anything further. For demos, drive the ANPR narrative from the
simulator and use the real worker to show the edge pipeline exists.
