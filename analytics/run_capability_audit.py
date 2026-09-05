"""Real, one-camera-at-a-time CV capability verification.

Runs the actual edge pipeline (via control_server.py's monitor/start,
identical to what the Investigate page drives) against ONE camera at a
time — never concurrently — for a bounded window each, then records exactly
what it really found as a CameraCapabilityRun row on the backend.

Why one at a time, not all together: running several camera pipelines
concurrently means they compete for this machine's CPU, and a session
earlier today measured that competition directly — 6 concurrent camera
pipelines pinned the process at 1200-1400% CPU and made the *browser*
sluggish too (same machine, same CPU budget). Running cameras sequentially
gives each one a genuinely unshared, fast pass, and produces a clean,
comparable, per-camera result instead of six pipelines all fighting for the
same cycles.

When to use this vs. offline_capture.py: this script needs control_server.py
AND the backend both running live, and posts each camera's real-time result
as it finishes — good for a quick live check while you're already working
with the stack up. offline_capture.py needs neither running during capture
(writes to a local SQLite file instead, replayed in once the backend is back
up) and supports true concurrent capture across many cameras when the web
stack is intentionally down and there's no live UI to protect from CPU
contention — better for a large, unattended sweep.

Usage:
    cd analytics
    .venv/bin/python run_capability_audit.py                    # default 9 Tier-A cameras
    .venv/bin/python run_capability_audit.py --cameras 4,6,12    # specific cameras
    .venv/bin/python run_capability_audit.py --duration 90       # seconds per camera

Requires control_server.py already running on :8800 (with SENTINEL_EMAIL /
SENTINEL_PASSWORD in its environment) and the backend on :8000.
"""
import argparse
import base64
import sys
import time
from datetime import datetime, timezone

import httpx

CONTROL_BASE = "http://localhost:8800"
BACKEND_BASE = "http://localhost:8000/api/v1"

# The 9 Sentinel cameras whose operator capability audit (CLAUDE.md /
# seed_data.py CAMERA_CAPABILITY_NOTES) says plate + face are genuinely
# legible — the only cameras where a "0 plates found" result means
# something rather than confirming a known optical limitation.
DEFAULT_CAMERAS = [4, 6, 7, 12, 16, 17, 21, 27, 30]

DUMMY_PLATE = "GJ00AUDIT001"  # mode=plate needs a target; detection passes run regardless of match


def run_one_camera(client: httpx.Client, camera_id: int, duration_s: float) -> dict:
    print(f"\n=== camera {camera_id}: starting isolated {duration_s:.0f}s run ===", flush=True)
    started_at = datetime.now(timezone.utc)

    resp = client.post(f"{CONTROL_BASE}/api/local/monitor/start",
                       json={"mode": "plate", "plate": DUMMY_PLATE, "camera_ids": [camera_id]})
    resp.raise_for_status()
    job_id = resp.json()["job_id"]

    time.sleep(duration_s)

    status = client.get(f"{CONTROL_BASE}/api/local/monitor/status").json()
    cam_stats = {}
    for job in status["jobs"]:
        if job["job_id"] == job_id:
            for c in job["cameras"]:
                if c["camera_id"] == camera_id:
                    cam_stats = c
    frames_processed = cam_stats.get("frames_processed", 0)
    anpr_stats = cam_stats.get("anpr_stats", {})

    client.post(f"{CONTROL_BASE}/api/local/monitor/{job_id}/stop")
    ended_at = datetime.now(timezone.utc)
    print(f"    frames_processed={frames_processed} anpr_stats={anpr_stats}", flush=True)

    # Real detections this run actually produced, from the backend's own
    # record of them — not re-derived from the pipeline's in-memory counters,
    # which is what makes this an independent verification rather than the
    # pipeline grading its own homework.
    events_resp = client.get(f"{BACKEND_BASE}/analytics/events",
                             params={"camera_id": camera_id, "source": "edge_worker", "limit": 300})
    events = [e for e in events_resp.json()["items"] if e["timestamp"] >= started_at.isoformat()]
    person_n = sum(1 for e in events if e["event_type"] == "person")
    vehicle_n = sum(1 for e in events if e["event_type"] == "vehicle")
    face_n = sum(1 for e in events if e["event_type"] == "face")

    anpr_resp = client.get(f"{BACKEND_BASE}/analytics/anpr",
                           params={"camera_id": camera_id, "source": "edge_worker", "hours": 1, "limit": 100})
    plates_found = sorted({
        e["plate_text"] for e in anpr_resp.json()["items"]
        if e["timestamp"] >= started_at.isoformat()
    })

    best = max(
        (e for e in events if e.get("has_evidence_image")),
        key=lambda e: e["confidence"], default=None,
    )
    best_evidence_b64, best_label = None, None
    if best:
        img = client.get(f"{BACKEND_BASE}/analytics/events/{best['id']}/evidence")
        if img.status_code == 200:
            best_evidence_b64 = base64.b64encode(img.content).decode("ascii")
            best_label = f"{best['event_type']} · {best['confidence']*100:.0f}%"

    print(f"    real detections this run: person={person_n} vehicle={vehicle_n} face={face_n} "
          f"plates={plates_found or 'none'}", flush=True)

    payload = {
        "camera_id": camera_id,
        "started_at": started_at.isoformat(), "ended_at": ended_at.isoformat(),
        "frames_processed": frames_processed,
        "person_detections": person_n, "vehicle_detections": vehicle_n,
        "face_detections": face_n, "face_matches": cam_stats.get("faces_matched", 0),
        "anpr_stats": anpr_stats, "plates_found": plates_found,
        "best_evidence_b64": best_evidence_b64, "best_evidence_label": best_label,
        "notes": None,
    }
    r = client.post(f"{BACKEND_BASE}/cameras/{camera_id}/capability-runs", json=payload, timeout=30)
    r.raise_for_status()
    print(f"    stored as capability run #{r.json()['id']}", flush=True)
    return payload


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cameras", default=",".join(str(c) for c in DEFAULT_CAMERAS),
                    help="comma-separated camera ids")
    ap.add_argument("--duration", type=float, default=75.0, help="seconds per camera")
    args = ap.parse_args()
    camera_ids = [int(c) for c in args.cameras.split(",") if c.strip()]

    with httpx.Client(timeout=30) as client:
        try:
            client.get(f"{CONTROL_BASE}/api/local/health").raise_for_status()
        except Exception as exc:
            sys.exit(f"control_server not reachable at {CONTROL_BASE}: {exc}")

        results = []
        for cid in camera_ids:
            try:
                results.append(run_one_camera(client, cid, args.duration))
            except Exception as exc:
                print(f"    camera {cid} FAILED: {exc}", flush=True)

    print("\n=== summary ===")
    for r in results:
        print(f"cam{r['camera_id']:02d}: frames={r['frames_processed']:4d}  "
              f"person={r['person_detections']:3d} vehicle={r['vehicle_detections']:3d} "
              f"face={r['face_detections']:3d}  plates={r['plates_found'] or '-'}")


if __name__ == "__main__":
    main()
