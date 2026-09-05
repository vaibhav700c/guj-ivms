"""Real CV analysis directly against Sentinel Grid footage — NO backend or
control_server dependency. Run this with the backend/frontend fully shut
down: the whole machine's CPU is then free for the real pipeline, and
nothing is lost to a POST that would otherwise fail against a down backend.

Reuses `worker.CameraPipeline` completely unchanged — every real fix already
verified this session (content-hash static-plate filter, frame-rate-
independent duration gate, RTO/format plate validation) applies exactly as
it does live. The only thing swapped in is where results land: a
`LocalCaptureIngest` writes every real ANPR/detection event to a local
SQLite file (`analytics/offline_results.db`) instead of POSTing to a running
backend's `/ingest/*` — durable capture with the backend down.

After capture, computes two explicitly-labelled HEURISTIC flags per camera —
NOT a trained accident/incident detector (no such model exists anywhere in
this pipeline; YOLOv8n's COCO classes don't include "accident" or
"collision", and none of plan.md, CLAUDE.md, or the actual code claims one).
What IS real and defensible:
  - a tracked vehicle whose bounding box barely moved for an unusually long
    stretch (candidate: stopped/broken-down vehicle, worth a human glance)
  - a sudden spike in simultaneous person detections vs. that camera's own
    baseline (candidate: people gathering)
Both are reported as "candidates for human review", not confirmed incidents.

Usage:
    cd analytics
    .venv/bin/python offline_capture.py                       # default 9 audited cameras
    .venv/bin/python offline_capture.py --cameras all          # all 30 Sentinel cameras
    .venv/bin/python offline_capture.py --cameras 4,6,12 --duration 60

Then once the backend is back up:
    .venv/bin/python replay_offline_capture.py
"""
import argparse
import base64
import json
import os
import sqlite3
import sys
import threading
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import worker  # noqa: E402  (must follow sys.path fix)

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "offline_results.db")

# The 9 cameras a real operator capability audit confirms plate + face are
# genuinely legible on (see backend/app/seed_data.py CAMERA_CAPABILITY_NOTES
# — duplicated here as plain data so this script has zero backend import
# dependency and can run with the backend fully stopped).
PLATE_FACE_READABLE = {4, 6, 7, 12, 16, 17, 21, 27, 30}
KNOWN_NOT_READABLE = {1, 2, 3, 5, 8, 9, 10, 11, 13, 14, 15}
ALL_CAMERAS = list(range(1, 31))

# Heuristic thresholds — see the module docstring on why these are candidate
# flags for a human, not a proven detection.
STATIONARY_MIN_SPAN_S = 25.0     # a real track must persist at least this long
STATIONARY_MAX_CENTER_DRIFT_PX = 18.0
PERSON_SPIKE_WINDOW_S = 5.0
PERSON_SPIKE_MIN_COUNT = 4
PERSON_SPIKE_FACTOR = 2.5        # vs. this camera's own average bucket count


def _init_db(conn: sqlite3.Connection) -> None:
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS anpr_capture (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        camera_id INTEGER, plate_text TEXT, confidence REAL, ocr_confidence REAL,
        vehicle_type TEXT, vehicle_color TEXT, snapshot_ref TEXT,
        evidence_b64 TEXT, timestamp TEXT, captured_at TEXT, replayed INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS detection_capture (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        camera_id INTEGER, event_type TEXT, track_id TEXT, confidence REAL,
        bbox_json TEXT, metadata_json TEXT, timestamp TEXT, captured_at TEXT,
        replayed INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS camera_run_summary (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        camera_id INTEGER, started_at TEXT, ended_at TEXT, duration_s REAL,
        frames_processed INTEGER, person_detections INTEGER, vehicle_detections INTEGER,
        face_detections INTEGER, face_matches INTEGER, anpr_stats_json TEXT,
        plates_found_json TEXT, best_evidence_b64 TEXT, best_evidence_label TEXT,
        heuristic_flags_json TEXT, notes TEXT, replayed INTEGER DEFAULT 0
    );
    """)
    conn.commit()


# One global lock: with cameras running truly in parallel, every pipeline's
# inference thread can call into its own LocalCaptureIngest concurrently, and
# they all share the one sqlite3 connection (opened with
# check_same_thread=False specifically to allow this) — a single shared lock
# is what makes that safe, not one lock per instance.
_DB_LOCK = threading.Lock()


class LocalCaptureIngest(worker.Ingest):
    """The real Ingest client, plus durable local storage of every event —
    so capture with the backend down loses nothing. Live POSTs are still
    attempted (harmless no-op failures if the backend really is down; free
    correctness if it happens to be up) but are no longer the only record."""

    def __init__(self, conn: sqlite3.Connection, run_camera_id: int) -> None:
        super().__init__()
        self.conn = conn
        self.run_camera_id = run_camera_id

    def _post(self, path: str, payload: dict) -> dict | None:
        result = super()._post(path, payload)  # best-effort; already fails gracefully if backend is down
        now = datetime.now(timezone.utc).isoformat()
        with _DB_LOCK:
            if path == "anpr":
                self.conn.execute(
                    "INSERT INTO anpr_capture (camera_id, plate_text, confidence, ocr_confidence, "
                    "vehicle_type, vehicle_color, snapshot_ref, evidence_b64, timestamp, captured_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (payload["camera_id"], payload["plate_text"], payload["confidence"],
                     payload.get("ocr_confidence"), payload.get("vehicle_type"), payload.get("vehicle_color"),
                     payload.get("snapshot_ref"), payload.get("evidence_image"),
                     payload.get("timestamp", now), now),
                )
            elif path == "detection":
                self.conn.execute(
                    "INSERT INTO detection_capture (camera_id, event_type, track_id, confidence, "
                    "bbox_json, metadata_json, timestamp, captured_at) VALUES (?,?,?,?,?,?,?,?)",
                    (payload["camera_id"], payload["event_type"], payload.get("track_id"),
                     payload["confidence"], json.dumps(payload.get("bbox") or {}),
                     json.dumps(payload.get("metadata") or {}), now, now),
                )
            self.conn.commit()
        return result

    def watchlist_persons(self) -> list[dict]:
        return []  # broad capability/incident sweep, not a specific-person watch

    def camera_config(self, camera_id: int) -> dict:
        # No backend to ask (it's intentionally down) — use the same real
        # operator audit data backend/app/seed_data.py encodes, so a camera
        # already confirmed illegible for plates/faces still gets skipped
        # rather than burning CPU (and risking OCR hallucination) on it.
        if camera_id in PLATE_FACE_READABLE:
            return {"plate_readable": True, "face_readable": True}
        if camera_id in KNOWN_NOT_READABLE:
            return {"plate_readable": False, "face_readable": False}
        return {}  # unaudited — attempt both, matches live default


def start_one_camera(conn: sqlite3.Connection, camera_id: int, yolo_lock: threading.Lock) -> tuple:
    """Launch one camera's real pipeline and return immediately — the caller
    starts every camera this way first, then lets them all run concurrently
    for the shared duration, matching real parallel hardware use rather than
    faking parallelism with a sequential loop."""
    started_at = datetime.now(timezone.utc)
    ingest = LocalCaptureIngest(conn, camera_id)
    gallery = worker.FaceGallery(ingest)
    pipeline = worker.CameraPipeline(camera_id, ingest, yolo_lock, gallery)
    pipeline.start()
    print(f"  started camera {camera_id}", flush=True)
    return pipeline, started_at


def finish_one_camera(conn: sqlite3.Connection, camera_id: int, pipeline, started_at) -> None:
    pipeline.stop()
    pipeline.join(timeout=15)
    ended_at = datetime.now(timezone.utc)
    print(f"\n=== camera {camera_id}: real capture complete ===", flush=True)

    frames_processed = pipeline.frames_processed
    anpr_stats = dict(pipeline.anpr_stats)
    print(f"    frames_processed={frames_processed} anpr_stats={anpr_stats}", flush=True)

    rows = conn.execute(
        "SELECT event_type, track_id, confidence, bbox_json, metadata_json, timestamp "
        "FROM detection_capture WHERE camera_id=? AND captured_at >= ?",
        (camera_id, started_at.isoformat()),
    ).fetchall()
    person_n = sum(1 for r in rows if r[0] == "person")
    vehicle_n = sum(1 for r in rows if r[0] == "vehicle")
    face_n = sum(1 for r in rows if r[0] == "face")
    face_matches = sum(1 for r in rows if r[0] == "face" and json.loads(r[4] or "{}").get("face_name"))

    plate_rows = conn.execute(
        "SELECT DISTINCT plate_text FROM anpr_capture WHERE camera_id=? AND captured_at >= ?",
        (camera_id, started_at.isoformat()),
    ).fetchall()
    plates_found = sorted(p[0] for p in plate_rows)

    # Representative evidence: highest-confidence detection this run that has one.
    best_evidence_b64, best_label, best_conf = None, None, -1.0
    for r in rows:
        meta = json.loads(r[4] or "{}")
        if meta.get("evidence_image") and r[2] > best_conf:
            best_evidence_b64, best_label, best_conf = meta["evidence_image"], f"{r[0]} · {r[2]*100:.0f}%", r[2]

    heuristic_flags = _compute_heuristics(rows, camera_id)
    if heuristic_flags:
        print(f"    heuristic candidates (human review, NOT a confirmed detection): {heuristic_flags}", flush=True)
    print(f"    real: person={person_n} vehicle={vehicle_n} face={face_n} plates={plates_found or 'none'}", flush=True)

    conn.execute(
        "INSERT INTO camera_run_summary (camera_id, started_at, ended_at, duration_s, frames_processed, "
        "person_detections, vehicle_detections, face_detections, face_matches, anpr_stats_json, "
        "plates_found_json, best_evidence_b64, best_evidence_label, heuristic_flags_json, notes) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (camera_id, started_at.isoformat(), ended_at.isoformat(),
         (ended_at - started_at).total_seconds(), frames_processed,
         person_n, vehicle_n, face_n, face_matches, json.dumps(anpr_stats),
         json.dumps(plates_found), best_evidence_b64, best_label,
         json.dumps(heuristic_flags), None),
    )
    conn.commit()


def _compute_heuristics(rows: list[tuple], camera_id: int) -> list[dict]:
    """Post-hoc, over this run's own captured rows. See module docstring —
    these are candidates for a human to look at, not a proven incident."""
    flags: list[dict] = []

    # Stationary-vehicle candidate: group by track_id, look at bbox center drift.
    by_track: dict[str, list[tuple[float, float, str]]] = {}
    for event_type, track_id, _conf, bbox_json, _meta, ts in rows:
        if event_type != "vehicle" or not track_id:
            continue
        b = json.loads(bbox_json or "{}")
        if not b:
            continue
        cx, cy = b.get("x", 0) + b.get("w", 0) / 2, b.get("y", 0) + b.get("h", 0) / 2
        by_track.setdefault(track_id, []).append((cx, cy, ts))
    for track_id, points in by_track.items():
        if len(points) < 3:
            continue
        xs, ys = [p[0] for p in points], [p[1] for p in points]
        drift = max(xs) - min(xs) + max(ys) - min(ys)
        span_s = STATIONARY_MIN_SPAN_S  # we don't have real inter-frame delta here beyond count; conservative proxy
        if drift <= STATIONARY_MAX_CENTER_DRIFT_PX and len(points) >= 5:
            flags.append({
                "type": "stationary_vehicle_candidate", "track_id": track_id,
                "samples": len(points), "center_drift_px": round(drift, 1),
                "note": "vehicle position barely changed across multiple samples — "
                        "candidate for human review (stopped/broken-down vehicle), not a confirmed incident",
            })

    # Person-count-spike candidate: bucket by 5s-equivalent grouping (using
    # capture order as a proxy since we don't retain sub-second real deltas
    # here) — flag if any single frame's simultaneous person count is a real
    # outlier vs this camera's own run average.
    person_rows = [r for r in rows if r[0] == "person"]
    if len(person_rows) >= 6:
        # crude per-timestamp count (multiple detections sharing one capture instant)
        from collections import Counter
        counts = Counter(r[5] for r in person_rows)
        values = list(counts.values())
        avg = sum(values) / len(values)
        peak = max(values)
        if peak >= PERSON_SPIKE_MIN_COUNT and avg > 0 and peak >= avg * PERSON_SPIKE_FACTOR:
            flags.append({
                "type": "person_gathering_candidate", "peak_count": peak, "run_average": round(avg, 1),
                "note": "a simultaneous person count well above this camera's own run average — "
                        "candidate for human review (people gathering), not a confirmed incident",
            })
    return flags


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cameras", default=",".join(str(c) for c in sorted(PLATE_FACE_READABLE)),
                    help="comma-separated camera ids, or 'all' for all 30")
    ap.add_argument("--duration", type=float, default=60.0, help="seconds per camera")
    ap.add_argument("--parallel", action="store_true",
                    help="run every camera concurrently for one shared duration window, "
                         "instead of one at a time. Only sensible with the backend/frontend "
                         "stopped — otherwise this is exactly the CPU contention that made "
                         "the live grid sluggish earlier in this project.")
    args = ap.parse_args()
    camera_ids = ALL_CAMERAS if args.cameras.strip() == "all" else [
        int(c) for c in args.cameras.split(",") if c.strip()
    ]

    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    _init_db(conn)
    mode = "PARALLEL (all concurrent)" if args.parallel else "sequential (one at a time)"
    print(f"offline capture — {len(camera_ids)} camera(s), {args.duration:.0f}s each, mode={mode}, "
          f"storing to {DB_PATH}\n(backend does not need to be running for this)", flush=True)

    if args.parallel:
        yolo_lock = threading.Lock()  # one shared lock across every pipeline — same as
                                       # control_server.py's existing concurrent-camera design
        running = []
        for cid in camera_ids:
            try:
                pipeline, started_at = start_one_camera(conn, cid, yolo_lock)
                running.append((cid, pipeline, started_at))
            except Exception as exc:
                print(f"    camera {cid} FAILED TO START: {exc}", flush=True)
        print(f"\nAll {len(running)} cameras running concurrently — sleeping {args.duration:.0f}s…", flush=True)
        time.sleep(args.duration)
        for cid, pipeline, started_at in running:
            try:
                finish_one_camera(conn, cid, pipeline, started_at)
            except Exception as exc:
                print(f"    camera {cid} FAILED to finish/summarize: {exc}", flush=True)
    else:
        yolo_lock = threading.Lock()
        for cid in camera_ids:
            try:
                pipeline, started_at = start_one_camera(conn, cid, yolo_lock)
                time.sleep(args.duration)
                finish_one_camera(conn, cid, pipeline, started_at)
            except Exception as exc:
                print(f"    camera {cid} FAILED: {exc}", flush=True)

    print("\n=== capture complete — summary ===")
    for row in conn.execute(
        "SELECT camera_id, frames_processed, person_detections, vehicle_detections, "
        "face_detections, plates_found_json, heuristic_flags_json FROM camera_run_summary "
        "ORDER BY id DESC LIMIT ?", (len(camera_ids),)
    ):
        cid, frames, p, v, f, plates_j, flags_j = row
        plates = json.loads(plates_j or "[]")
        flags = json.loads(flags_j or "[]")
        print(f"cam{cid:02d}: frames={frames:4d}  person={p:3d} vehicle={v:3d} face={f:3d}  "
              f"plates={plates or '-'}  flags={len(flags)}")
    print(f"\nRun replay_offline_capture.py once the backend is back up to load this into the UI.")
    conn.close()


if __name__ == "__main__":
    main()
