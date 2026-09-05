"""Load a completed offline_capture.py run into the backend, once it's back up.

Reads analytics/offline_results.db and POSTs every captured row through the
SAME real endpoints a live edge worker uses (/ingest/anpr, /ingest/detection)
plus the per-camera summary to /cameras/{id}/capability-runs — so everything
shows up in the UI (Detections Viewer, ANPR Detections, Vehicle Search, the
Camera Registry's "Verified CV Capability" panel) exactly as if it had been
ingested live. Nothing here is invented: every row replayed was written by
offline_capture.py from a real detection against real Sentinel footage.

Marks each row `replayed=1` after a successful POST so re-running this
script is safe (won't duplicate already-loaded rows).

Usage:
    cd analytics
    .venv/bin/python replay_offline_capture.py               # replay everything not yet replayed
    .venv/bin/python replay_offline_capture.py --backend http://localhost:8000
"""
import argparse
import json
import sqlite3
import time

import httpx

DB_PATH = "offline_results.db"

# The backend's own RateLimiter (plan §17.1 Layer 5) allows 300 req/60s per
# client IP — generous for normal use, but a bulk replay firing everything
# at once trips it immediately (measured: 287/1739 rows landed before every
# further request got a 429). Pace comfortably under that.
REQUEST_DELAY_S = 0.4  # ~2.5/s -> 150/min, safely under the 300/60s cap


def replay_anpr(conn: sqlite3.Connection, client: httpx.Client, base: str) -> tuple[int, int]:
    rows = conn.execute(
        "SELECT id, camera_id, plate_text, confidence, ocr_confidence, vehicle_type, "
        "vehicle_color, snapshot_ref, evidence_b64, timestamp FROM anpr_capture WHERE replayed=0"
    ).fetchall()
    ok = 0
    for (rid, camera_id, plate_text, confidence, ocr_confidence, vehicle_type,
         vehicle_color, snapshot_ref, evidence_b64, timestamp) in rows:
        payload = {
            "camera_id": camera_id, "plate_text": plate_text, "confidence": confidence,
            "ocr_confidence": ocr_confidence, "vehicle_type": vehicle_type,
            "vehicle_color": vehicle_color, "snapshot_ref": snapshot_ref,
            "evidence_image": evidence_b64, "timestamp": timestamp, "source": "edge-yolo",
        }
        try:
            r = client.post(f"{base}/api/v1/ingest/anpr", json=payload, timeout=15)
            time.sleep(REQUEST_DELAY_S)
            if r.status_code in (200, 201):
                conn.execute("UPDATE anpr_capture SET replayed=1 WHERE id=?", (rid,))
                ok += 1
            else:
                print(f"  anpr row {rid} -> HTTP {r.status_code}: {r.text[:150]}")
        except Exception as exc:
            print(f"  anpr row {rid} failed: {exc}")
    conn.commit()
    return ok, len(rows)


def replay_detections(conn: sqlite3.Connection, client: httpx.Client, base: str) -> tuple[int, int]:
    rows = conn.execute(
        "SELECT id, camera_id, event_type, track_id, confidence, bbox_json, metadata_json "
        "FROM detection_capture WHERE replayed=0"
    ).fetchall()
    ok = 0
    for (rid, camera_id, event_type, track_id, confidence, bbox_json, metadata_json) in rows:
        payload = {
            "camera_id": camera_id, "event_type": event_type, "track_id": track_id,
            "confidence": confidence, "bbox": json.loads(bbox_json or "{}"),
            "metadata": json.loads(metadata_json or "{}"), "source": "edge-yolo",
        }
        try:
            r = client.post(f"{base}/api/v1/ingest/detection", json=payload, timeout=15)
            time.sleep(REQUEST_DELAY_S)
            if r.status_code in (200, 201):
                conn.execute("UPDATE detection_capture SET replayed=1 WHERE id=?", (rid,))
                ok += 1
            else:
                print(f"  detection row {rid} -> HTTP {r.status_code}: {r.text[:150]}")
        except Exception as exc:
            print(f"  detection row {rid} failed: {exc}")
    conn.commit()
    return ok, len(rows)


def replay_summaries(conn: sqlite3.Connection, client: httpx.Client, base: str) -> tuple[int, int]:
    rows = conn.execute(
        "SELECT id, camera_id, started_at, ended_at, frames_processed, person_detections, "
        "vehicle_detections, face_detections, face_matches, anpr_stats_json, plates_found_json, "
        "best_evidence_b64, best_evidence_label, heuristic_flags_json, notes "
        "FROM camera_run_summary WHERE replayed=0"
    ).fetchall()
    ok = 0
    for (rid, camera_id, started_at, ended_at, frames_processed, person_n, vehicle_n,
         face_n, face_matches, anpr_stats_json, plates_json, best_b64, best_label,
         flags_json, notes) in rows:
        heuristic_flags = json.loads(flags_json or "[]")
        note_text = notes or ""
        if heuristic_flags:
            note_text = (note_text + "\n" if note_text else "") + "; ".join(
                f"[HEURISTIC candidate, not confirmed] {f['type']}: {f['note']}" for f in heuristic_flags
            )
        payload = {
            "camera_id": camera_id, "started_at": started_at, "ended_at": ended_at,
            "frames_processed": frames_processed, "person_detections": person_n,
            "vehicle_detections": vehicle_n, "face_detections": face_n, "face_matches": face_matches,
            "anpr_stats": json.loads(anpr_stats_json or "{}"), "plates_found": json.loads(plates_json or "[]"),
            "best_evidence_b64": best_b64, "best_evidence_label": best_label, "notes": note_text or None,
        }
        try:
            r = client.post(f"{base}/api/v1/cameras/{camera_id}/capability-runs", json=payload, timeout=15)
            time.sleep(REQUEST_DELAY_S)
            if r.status_code in (200, 201):
                conn.execute("UPDATE camera_run_summary SET replayed=1 WHERE id=?", (rid,))
                ok += 1
            else:
                print(f"  summary row {rid} (cam{camera_id}) -> HTTP {r.status_code}: {r.text[:150]}")
        except Exception as exc:
            print(f"  summary row {rid} (cam{camera_id}) failed: {exc}")
    conn.commit()
    return ok, len(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--backend", default="http://localhost:8000")
    ap.add_argument("--db", default=DB_PATH)
    args = ap.parse_args()

    with httpx.Client() as client:
        try:
            client.get(f"{args.backend}/health", timeout=10).raise_for_status()
        except Exception as exc:
            raise SystemExit(f"backend not reachable at {args.backend}: {exc}")

        conn = sqlite3.connect(args.db)
        print("Replaying ANPR events…")
        a_ok, a_total = replay_anpr(conn, client, args.backend)
        print(f"  {a_ok}/{a_total} new rows loaded")

        print("Replaying detection events…")
        d_ok, d_total = replay_detections(conn, client, args.backend)
        print(f"  {d_ok}/{d_total} new rows loaded")

        print("Replaying per-camera capability-run summaries…")
        s_ok, s_total = replay_summaries(conn, client, args.backend)
        print(f"  {s_ok}/{s_total} new rows loaded")

        conn.close()
    print("\nDone — check /detections, /anpr, /vehicles, and the Camera Registry drawer in the UI.")


if __name__ == "__main__":
    main()
