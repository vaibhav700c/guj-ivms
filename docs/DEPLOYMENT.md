# Deployment — Vercel (frontend) + Render (backend + PostgreSQL)

> ✅ **Already deployed** — UI: https://guj-ivms.vercel.app · API: https://guj-ivms-api.onrender.com
> Render service: `guj-ivms-api` (srv-daasn4ss728c73e22ocg) · Postgres: `guj-ivms-db` (dpg-daasmtoae00c73al6230-a, oregon)

The steps below document how this deployment was created and how to reproduce it.

## 1. Render backend (Blueprint)

1. Push this repo to GitHub (done via `gh repo create`).
2. Render dashboard → **New → Blueprint** → pick the repo → Apply.
   This creates `guj-ivms-api` (Docker web service) and `guj-ivms-db` (free Postgres)
   exactly as defined in `render.yaml`.
3. After the first deploy, copy the service URL, e.g. `https://guj-ivms-api.onrender.com`.
4. Environment → set `CORS_ORIGINS` to the Vercel URL (step 2 below), e.g.
   `https://guj-ivms.vercel.app`.
5. Verify: `curl https://guj-ivms-api.onrender.com/health` → `{"status":"ok",...}`
   First boot auto-seeds 50 cameras, watchlist, VAHAN records, and users. The
   demo simulator stays off (`SIMULATOR_AUTO_START=false`) — start it
   deliberately (Dashboard toggle or `POST /api/v1/simulator/start`) when you
   want a live-events demo without real cameras; every row it writes is
   stamped `source="simulator"` and never shown as a genuine detection.

## 2. Vercel frontend

CLI (already authenticated locally):

```bash
cd frontend
vercel link
vercel env add VITE_API_URL production    # https://guj-ivms-api.onrender.com
vercel env add VITE_WS_URL production     # wss://guj-ivms-api.onrender.com
```

> **Root directory:** the project must use **`frontend`** as its Root Directory
> (set via `vercel project` settings or dashboard Settings → General).
> In this repo it was configured through the Vercel API; git pushes to `master`
> auto-deploy after that.

```bash
vercel git connect https://github.com/vaibhav700c/guj-ivms   # enable auto-deploy
vercel --prod
```

Or dashboard: Import repo → **Root Directory: `frontend`** → framework auto-detects
Vite (see `frontend/vercel.json`) → add the two `VITE_*` env vars → Deploy.

## 3. Smoke test the deployed product

1. Open the Vercel URL → the top-bar "Real detections only" toggle is ON by
   default, so the Dashboard starts empty until real events arrive.
2. Turn the Dashboard's "Analytics Simulator" on (or turn the top-bar toggle
   off) to see fabricated demo data — every row it produces is tagged
   `source: "simulator"` and rendered with an amber **SIMULATED** badge.
3. **Live Alerts** page → with the simulator running, alerts stream over
   WebSocket every few seconds (watchlist hits from the demo simulator).
4. **Vehicle Search** → `GJ 01 AB 1234` → with the simulator running and
   "Real detections only" off, journey map + timeline fills as the tracked
   demo vehicle crosses cameras. With the toggle on, this fabricated plate
   correctly returns no sightings.
5. **Live View** → 3×3 control-room grid; **GIS Map** → 50 cameras state-wide.

## 4. Going beyond the demo

- `SIMULATOR_AUTO_START` already defaults to `false` in `render.yaml`. Point
  edge nodes at `POST /api/v1/ingest/anpr` with header
  `X-API-Key: <INGEST_API_KEY>`.
- Set `REQUIRE_AUTH=true` to enforce JWT; login remains `POST /api/v1/auth/login`.
- Add Redis (Render key-value or Upstash) and set `REDIS_URL` for multi-replica
  WebSocket fan-out.
