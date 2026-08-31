# Deployment — Vercel (frontend) + Render (backend + PostgreSQL)

## 1. Render backend (Blueprint)

1. Push this repo to GitHub (done via `gh repo create`).
2. Render dashboard → **New → Blueprint** → pick the repo → Apply.
   This creates `guj-ivms-api` (Docker web service) and `guj-ivms-db` (free Postgres)
   exactly as defined in `render.yaml`.
3. After the first deploy, copy the service URL, e.g. `https://guj-ivms-api.onrender.com`.
4. Environment → set `CORS_ORIGINS` to the Vercel URL (step 2 below), e.g.
   `https://guj-ivms.vercel.app`.
5. Verify: `curl https://guj-ivms-api.onrender.com/health` → `{"status":"ok",...}`
   First boot auto-seeds 50 cameras, watchlist, VAHAN records, and users, and
   starts the demo simulator (`SIMULATOR_AUTO_START=true`).

## 2. Vercel frontend

CLI (already authenticated locally):

```bash
cd frontend
vercel link
vercel env add VITE_API_URL production    # https://guj-ivms-api.onrender.com
vercel env add VITE_WS_URL production     # wss://guj-ivms-api.onrender.com
vercel --prod
```

Or dashboard: Import repo → **Root Directory: `frontend`** → framework auto-detects
Vite (see `frontend/vercel.json`) → add the two `VITE_*` env vars → Deploy.

## 3. Smoke test the deployed product

1. Open the Vercel URL → Dashboard shows live ANPR counters within ~10 s.
2. **Live Alerts** page → alerts stream over WebSocket every few seconds
   (watchlist hits from the demo simulator).
3. **Vehicle Search** → `GJ 01 AB 1234` → journey map + timeline fills as the
   tracked vehicle crosses cameras.
4. **Live View** → 3×3 control-room grid; **GIS Map** → 50 cameras state-wide.

## 4. Going beyond the demo

- Set `SIMULATOR_AUTO_START=false` and point edge nodes at
  `POST /api/v1/ingest/anpr` with header `X-API-Key: <INGEST_API_KEY>`.
- Set `REQUIRE_AUTH=true` to enforce JWT; login remains `POST /api/v1/auth/login`.
- Add Redis (Render key-value or Upstash) and set `REDIS_URL` for multi-replica
  WebSocket fan-out.
