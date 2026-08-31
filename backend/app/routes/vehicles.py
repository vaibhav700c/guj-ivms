"""Vehicle routes — registry lookup, ANPR search, journey reconstruction (plan §7)."""
import math
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.alert_engine import normalize_plate
from app.db import get_db
from app.models import ANPREvent, Camera, VehicleRecord

router = APIRouter(prefix="/vehicles", tags=["vehicles"])


def haversine_km(lat1, lng1, lat2, lng2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _registry_query(db: Session, norm: str):
    return db.query(VehicleRecord).filter(
        func.upper(func.replace(func.replace(VehicleRecord.registration_number, " ", ""), "-", ""))
        == norm
    ).first()


@router.get("/search/{plate}")
def search_vehicle(plate: str, db: Session = Depends(get_db)):
    """Full timeline for a plate: registry + all ANPR sightings + journey legs."""
    norm = normalize_plate(plate)
    record = _registry_query(db, norm)
    events = (
        db.query(ANPREvent)
        .filter(ANPREvent.plate_normalized == norm)
        .order_by(ANPREvent.timestamp.asc())
        .all()
    )
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
        })

    # Probable (OCR-tolerant) matches — plan §20.2 step 5 (ReID/fuzzy fallback)
    from difflib import SequenceMatcher

    other_events = (
        db.query(ANPREvent)
        .filter(ANPREvent.plate_normalized != norm)
        .order_by(ANPREvent.timestamp.desc())
        .limit(500)
        .all()
    )
    seen_plates: set[str] = set()
    for e in other_events:
        if e.plate_normalized in seen_plates:
            continue
        ratio = SequenceMatcher(None, norm, e.plate_normalized).ratio()
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
        "legs": legs,
    }


@router.get("/journey/{plate}")
def journey_reconstruction(plate: str, db: Session = Depends(get_db)):
    """Reconstructed route with GIS — alias for full search (plan §13 vehicles/journey)."""
    data = search_vehicle(plate, db)
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
def last_seen(plate: str, db: Session = Depends(get_db)):
    """Most recent sighting of a plate (plan §13 vehicles/last-seen)."""
    norm = normalize_plate(plate)
    event = (
        db.query(ANPREvent)
        .filter(ANPREvent.plate_normalized == norm)
        .order_by(ANPREvent.timestamp.desc())
        .first()
    )
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
    }


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
def recent_detections(limit: int = Query(50, le=200), db: Session = Depends(get_db)):
    events = db.query(ANPREvent).order_by(ANPREvent.timestamp.desc()).limit(limit).all()
    return {"items": [
        {
            "id": e.id,
            "plate": e.plate_text,
            "camera_name": e.camera.name if e.camera else None,
            "city": e.camera.city if e.camera else None,
            "vehicle_type": e.vehicle_type,
            "confidence": e.confidence,
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
def traffic_by_camera(limit: int = 10, db: Session = Depends(get_db)):
    rows = (
        db.query(Camera.name, Camera.city, func.count(ANPREvent.id).label("cnt"))
        .join(ANPREvent, ANPREvent.camera_id == Camera.id)
        .group_by(Camera.id)
        .order_by(func.count(ANPREvent.id).desc())
        .limit(limit)
        .all()
    )
    return [{"camera": name, "city": city, "events": cnt} for name, city, cnt in rows]
