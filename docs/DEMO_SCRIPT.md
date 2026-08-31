# Demo Script (2–3 min) — Test Scenario per plan §20.2

Use the live deployment: **https://guj-ivms.vercel.app** → backend auto-auth in demo mode.

## 0. Warm-up (0:00–0:15)
Open Dashboard. Point out live counters during narration:
- 50 cameras · 44 online · ANPR events climbing every ~2 s
- Watchlist 7 active entries · VAHAN-like registry 10 records

## 1. Watchlist cross-reference (0:15–0:50)
- Go to **Live Alerts**. Alerts stream in over WebSocket (sound on).
- Point out a `STOLEN vehicle GJ 01 AB 1234` alert with camera, confidence, FIR.
- Click **Acknowledge → Resolve** to show the workflow.
- Navigate to **Watchlist** → toggle a rule, mention severity/FIR linkage.

## 2. Designated-vehicle journey reconstruction (0:50–1:35)
- Go to **Vehicle Search**, type `GJ 01 AB 1234`, hit **Reconstruct Journey**.
- Show VAHAN registry card (owner, maker/model, RTO).
- Click **▶ Replay next sighting** repeatedly → map polyline grows across Gujarat;
  markers light up, legs show distance/elapsed/speed.
- Mention probable OCR matches (plan step 5) returned by fuzzy plate matching.

## 3. GIS & Registry (1:35–2:15)
- Go to **GIS Map**. Toggle *By Status* / *By Tier* coloring; enable *Coverage Zones*.
- Click a camera popup (detail, coordinates).
- Open **Analytics** → hour-of-day traffic, top cameras, detection pie,
  Tier A/B/C coverage; download CSV reports.

## 4. Unified Viewing (2:15–2:45)
- Go to **Live View** → switch 2×2 / 3×3 / 4×4 grids; expand a camera to fullscreen.
- Explain: MediaMTX converts RTSP→WebRTC/HLS in the full docker-compose stack;
  simulator tiles stand in for the hackathon.

## Closing line
> "Analytics at the edge, correlation at the center — raw video never leaves the
> departments, only metadata and alerts. 100% open-source, deployed on Vercel + Render."