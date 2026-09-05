"""Vehicle routes — registry lookup, ANPR search, journey reconstruction (plan §7)."""
import base64
import math
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.alert_engine import normalize_plate
from app.db import get_db
from app.models import ANPREvent, Camera, DetectionEvent, VehicleRecord

router = APIRouter(prefix="/vehicles", tags=["vehicles"])


def haversine_km(lat1, lng1, lat2, lng2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _hist_similarity(a: list[float], b: list[float]) -> float:
    """Histogram intersection of two L1-normalized HSV histograms — 1.0 =
    identical color distribution, 0.0 = disjoint. Pure Python (no numpy/cv2
    dependency on the backend, unlike the edge worker that computes these)."""
    if not a or not b or len(a) != len(b):
        return 0.0
    return sum(min(x, y) for x, y in zip(a, b))


REID_TIME_WINDOW_MIN = 45
REID_SIMILARITY_THRESHOLD = 0.85


def _appearance_probable_matches(db: Session, sightings: list[dict], source: str | None = None) -> list[dict]:
    """Cross-camera vehicle matching for cameras that cannot read a plate at
    all (plan §7.2 Method 2 / Key Differentiator #3). For each confirmed ANPR
    sighting that carries an appearance signature (see
    analytics/worker.py::vehicle_appearance_signature), look for vehicle
    DetectionEvents on OTHER cameras within a plausible time window whose
    appearance histogram is a close match — these are cameras where the
    plate genuinely could not be read, so this is the only correlation
    signal available, same idea as plan's ReID/time-distance fallback.
    """
    from datetime import timedelta

    results = []
    seen: set[tuple[int, str]] = set()
    for s in sightings:
        sig = s.get("appearance_signature")
        if not sig:
            continue
        try:
            ts = datetime.fromisoformat(s["timestamp"])
        except Exception:
            continue
        window_start = ts - timedelta(minutes=REID_TIME_WINDOW_MIN)
        window_end = ts + timedelta(minutes=REID_TIME_WINDOW_MIN)
        cand_q = db.query(DetectionEvent).filter(
            DetectionEvent.event_type == "vehicle",
            DetectionEvent.camera_id != s["camera_id"],
            DetectionEvent.timestamp >= window_start,
            DetectionEvent.timestamp <= window_end,
        )
        if source:
            cand_q = cand_q.filter(DetectionEvent.source == source)
        candidates = cand_q.order_by(DetectionEvent.timestamp.desc()).limit(300).all()
        for c in candidates:
            csig = (c.metadata_json or {}).get("appearance_signature")
            if not csig:
                continue
            key = (c.camera_id, c.timestamp.isoformat())
            if key in seen:
                continue
            similarity = _hist_similarity(sig, csig)
            if similarity >= REID_SIMILARITY_THRESHOLD:
                seen.add(key)
                cam = db.get(Camera, c.camera_id)
                results.append({
                    "camera_id": c.camera_id,
                    "camera_name": cam.name if cam else None,
                    "lat": cam.latitude if cam else None,
                    "lng": cam.longitude if cam else None,
                    "city": cam.city if cam else None,
                    "timestamp": c.timestamp.isoformat(),
                    "similarity": round(similarity, 3),
                    "matched_from_camera": s["camera_name"],
                    "matched_from_timestamp": s["timestamp"],
                    "method": "appearance_reid",
                    "source": c.source,
                })
    results.sort(key=lambda r: r["similarity"], reverse=True)
    return results[:20]


def _registry_query(db: Session, norm: str):
    return db.query(VehicleRecord).filter(
        func.upper(func.replace(func.replace(VehicleRecord.registration_number, " ", ""), "-", ""))
        == norm
    ).first()


@router.get("")
def list_vehicles(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """List all VAHAN-like vehicle registry records (plan §19.2)."""
    total = db.query(VehicleRecord).count()
    records = db.query(VehicleRecord).offset(offset).limit(limit).all()
    return {
        "total": total,
        "items": [_vr_item(r) for r in records],
    }


def _vr_item(r: VehicleRecord) -> dict:
    return {
        "registration_number": r.registration_number,
        "owner_name": r.owner_name,
        "vehicle_class": r.vehicle_class,
        "maker": r.maker,
        "model": r.model,
        "color": r.color,
        "fuel_type": r.fuel_type,
        "rto_code": r.rto_code,
        "rto_name": r.rto_name,
        "insurance_valid_till": r.insurance_valid_till,
        "fitness_valid_till": r.fitness_valid_till,
    }


@router.get("/search/{plate}")
def search_vehicle(plate: str, source: str | None = None, db: Session = Depends(get_db)):
    """Full timeline for a plate: registry + all ANPR sightings + journey legs.

    `source` filters provenance ("edge_worker" | "simulator") — see CLAUDE.md
    "Two event sources". With `source=edge_worker`, a plate that only ever
    appeared in fabricated simulator events returns zero sightings rather
    than a partially-filtered, still-fabricated journey.
    """
    norm = normalize_plate(plate)
    record = _registry_query(db, norm)
    events_q = db.query(ANPREvent).options(joinedload(ANPREvent.camera)).filter(
        ANPREvent.plate_normalized == norm
    )
    if source:
        events_q = events_q.filter(ANPREvent.source == source)
    events = events_q.order_by(ANPREvent.timestamp.asc()).all()
    sightings = []
    probable = []
    for e in events:
        cam = e.camera
        sightings.append({
            "event_id": e.id,
            "camera_id": e.camera_id,
            "camera_name": cam.name if cam else None,
            "lat": cam.latitude if cam else None,
            "lng": cam.longitude if cam else None,
            "city": cam.city if cam else None,
            "timestamp": e.timestamp.isoformat() if e.timestamp else None,
            "direction": e.direction,
            "confidence": e.confidence,
            "vehicle_type": e.vehicle_type,
            "vehicle_color": e.vehicle_color,
            "snapshot_ref": e.snapshot_ref,
            "has_evidence_image": bool(e.evidence_image_b64),
            "source": e.source,
            "appearance_signature": (e.embedding or {}).get("appearance"),
        })

    # Probable (OCR-tolerant) matches — plan §20.2 step 5 (ReID/fuzzy fallback)
    from difflib import SequenceMatcher

    other_events_q = (
        db.query(ANPREvent)
        .options(joinedload(ANPREvent.camera))
        .filter(ANPREvent.plate_normalized != norm)
    )
    if source:
        other_events_q = other_events_q.filter(ANPREvent.source == source)
    other_events = other_events_q.order_by(ANPREvent.timestamp.desc()).limit(500).all()
    seen_plates: set[str] = set()
    for e in other_events:
        if e.plate_normalized in seen_plates:
            continue
        # Cheap prefilter before the O(n*m) ratio() call: real_quick_ratio()
        # and quick_ratio() are guaranteed upper bounds on ratio() (difflib
        # docs), so skipping candidates they've already ruled out can never
        # drop a genuine match — it only avoids computing the expensive exact
        # ratio for plates that are obviously too dissimilar.
        matcher = SequenceMatcher(None, norm, e.plate_normalized)
        if matcher.real_quick_ratio() < 0.85 or matcher.quick_ratio() < 0.85:
            continue
        ratio = matcher.ratio()
        if ratio >= 0.85:
            seen_plates.add(e.plate_normalized)
            cam = e.camera
            probable.append({
                "plate_text": e.plate_text,
                "similarity": round(ratio, 2),
                "camera_name": cam.name if cam else None,
                "lat": cam.latitude if cam else None,
                "lng": cam.longitude if cam else None,
                "city": cam.city if cam else None,
                "timestamp": e.timestamp.isoformat() if e.timestamp else None,
                "confidence": e.confidence,
                "source": e.source,
            })

    # Journey legs: distance, elapsed time, implied speed between consecutive sightings
    legs, total_km = [], 0.0
    for i in range(1, len(sightings)):
        a, b = sightings[i - 1], sightings[i]
        if None in (a["lat"], b["lat"]):
            continue
        dist = haversine_km(a["lat"], a["lng"], b["lat"], b["lng"])
        total_km += dist
        try:
            ta = datetime.fromisoformat(a["timestamp"])
            tb = datetime.fromisoformat(b["timestamp"])
            mins = max((tb - ta).total_seconds() / 60.0, 0.0)
        except Exception:
            mins = 0.0
        speed = (dist / (mins / 60.0)) if mins > 0.5 else None
        legs.append({
            "from_camera": a["camera_name"],
            "to_camera": b["camera_name"],
            "distance_km": round(dist, 2),
            "elapsed_min": round(mins, 1),
            "avg_speed_kmph": round(speed, 1) if speed and speed < 160 else None,
        })

    reid_matches = _appearance_probable_matches(db, sightings, source=source)
    for s in sightings:
        s.pop("appearance_signature", None)  # internal-only, not for the API response

    cities = list(dict.fromkeys(s["city"] for s in sightings if s["city"]))
    return {
        "plate": plate,
        "plate_normalized": norm,
        "registry": {
            "registration_number": record.registration_number,
            "owner_name": record.owner_name,
            "vehicle_class": record.vehicle_class,
            "maker": record.maker,
            "model": record.model,
            "color": record.color,
            "fuel_type": record.fuel_type,
            "insurance_valid_till": record.insurance_valid_till,
            "fitness_valid_till": record.fitness_valid_till,
            "rto_name": record.rto_name,
        } if record else None,
        "sightings_count": len(sightings),
        "total_distance_km": round(total_km, 2),
        "cities_visited": cities,
        "sightings": sightings,
        "probable_matches": probable,
        "probable_reid_matches": reid_matches,
        "legs": legs,
    }


@router.get("/journey/{plate}")
def journey_reconstruction(plate: str, source: str | None = None, db: Session = Depends(get_db)):
    """Reconstructed route with GIS — alias for full search (plan §13 vehicles/journey).

    `source` filters provenance — see CLAUDE.md "Two event sources".
    """
    data = search_vehicle(plate, source=source, db=db)
    return {
        "plate": data["plate"],
        "journey_start": data["sightings"][0]["timestamp"] if data["sightings"] else None,
        "journey_end": data["sightings"][-1]["timestamp"] if data["sightings"] else None,
        "waypoints": data["sightings"],
        "total_cameras": len(data["sightings"]),
        "total_distance_km": data["total_distance_km"],
        "cities_visited": data["cities_visited"],
        "probable_matches": data["probable_matches"],
    }


@router.get("/last-seen/{plate}")
def last_seen(plate: str, source: str | None = None, db: Session = Depends(get_db)):
    """Most recent sighting of a plate (plan §13 vehicles/last-seen).

    `source` filters provenance — see CLAUDE.md "Two event sources".
    """
    norm = normalize_plate(plate)
    q = db.query(ANPREvent).filter(ANPREvent.plate_normalized == norm)
    if source:
        q = q.filter(ANPREvent.source == source)
    event = q.order_by(ANPREvent.timestamp.desc()).first()
    if not event:
        raise HTTPException(404, "No sightings recorded for this plate")
    cam = event.camera
    return {
        "plate": event.plate_text,
        "camera_id": event.camera_id,
        "camera_name": cam.name if cam else None,
        "city": cam.city if cam else None,
        "lat": cam.latitude if cam else None,
        "lng": cam.longitude if cam else None,
        "timestamp": event.timestamp.isoformat() if event.timestamp else None,
        "direction": event.direction,
        "confidence": event.confidence,
        "snapshot_ref": event.snapshot_ref,
        "has_evidence_image": bool(event.evidence_image_b64),
        "source": event.source,
    }


@router.get("/events/{event_id}/evidence")
def event_evidence(event_id: int, db: Session = Depends(get_db)):
    """The real ANPR detection frame captured by the edge worker, if any."""
    event = db.get(ANPREvent, event_id)
    if not event or not event.evidence_image_b64:
        raise HTTPException(404, "No evidence frame on file for this event")
    return Response(content=base64.b64decode(event.evidence_image_b64), media_type="image/jpeg")


@router.get("/registry/{plate}")
def registry_lookup(plate: str, db: Session = Depends(get_db)):
    norm = normalize_plate(plate)
    record = _registry_query(db, norm)
    if not record:
        raise HTTPException(404, "No registry record found for this plate")
    return {
        "registration_number": record.registration_number,
        "owner_name": record.owner_name,
        "vehicle_class": record.vehicle_class,
        "maker": record.maker,
        "model": record.model,
        "color": record.color,
        "fuel_type": record.fuel_type,
        "registration_date": record.registration_date,
        "insurance_valid_till": record.insurance_valid_till,
        "fitness_valid_till": record.fitness_valid_till,
        "rto_code": record.rto_code,
        "rto_name": record.rto_name,
    }


@router.get("/recent")
def recent_detections(limit: int = Query(50, ge=1, le=200), source: str | None = None,
                      db: Session = Depends(get_db)):
    """`source` filters provenance — see CLAUDE.md "Two event sources"."""
    q = db.query(ANPREvent).options(joinedload(ANPREvent.camera))
    if source:
        q = q.filter(ANPREvent.source == source)
    events = q.order_by(ANPREvent.timestamp.desc()).limit(limit).all()
    return {"items": [
        {
            "id": e.id,
            "plate": e.plate_text,
            "camera_name": e.camera.name if e.camera else None,
            "city": e.camera.city if e.camera else None,
            "vehicle_type": e.vehicle_type,
            "confidence": e.confidence,
            "source": e.source,
            "timestamp": e.timestamp.isoformat() if e.timestamp else None,
        }
        for e in events
    ]}


@router.get("/traffic/by-hour")
def traffic_by_hour(db: Session = Depends(get_db)):
    if db.bind.dialect.name == "sqlite":
        rows = db.query(
            func.strftime("%H", ANPREvent.timestamp).label("hr"),
            func.count(ANPREvent.id),
        ).group_by("hr").all()
    else:
        rows = db.query(
            func.to_char(ANPREvent.timestamp, "HH24").label("hr"),
            func.count(ANPREvent.id),
        ).group_by("hr").all()
    counts = {str(hr): c for hr, c in rows}
    return [{"hour": f"{h:02d}:00", "count": counts.get(f"{h:02d}", 0)} for h in range(24)]


@router.get("/traffic/by-camera")
def traffic_by_camera(limit: int = Query(10, ge=1, le=100), db: Session = Depends(get_db)):
    rows = (
        db.query(Camera.name, Camera.city, func.count(ANPREvent.id).label("cnt"))
        .join(ANPREvent, ANPREvent.camera_id == Camera.id)
        .group_by(Camera.id)
        .order_by(func.count(ANPREvent.id).desc())
        .limit(limit)
        .all()
    )
    return [{"camera": name, "city": city, "events": cnt} for name, city, cnt in rows]
