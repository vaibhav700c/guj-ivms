"""Watchlist routes — CRUD for stolen/blacklisted vehicles & wanted persons."""
import csv
import io

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import WatchlistEntry
from app.security import get_current_user

router = APIRouter(prefix="/watchlist", tags=["watchlist"])


class WatchlistCreate(BaseModel):
    category: str = "stolen_vehicle"
    subject_type: str = "vehicle"
    identifier: str
    description: str | None = None
    severity: str = "high"
    fir_number: str | None = None
    police_station: str | None = None
    active: bool = True


class WatchlistUpdate(BaseModel):
    category: str | None = None
    description: str | None = None
    severity: str | None = None
    active: bool | None = None
    fir_number: str | None = None
    police_station: str | None = None


def serialize(w: WatchlistEntry) -> dict:
    return {
        "id": w.id,
        "category": w.category,
        "subject_type": w.subject_type,
        "identifier": w.identifier,
        "description": w.description,
        "severity": w.severity,
        "fir_number": w.fir_number,
        "police_station": w.police_station,
        "active": w.active,
        "created_at": w.created_at.isoformat() if w.created_at else None,
    }


@router.get("")
def list_entries(
    category: str | None = None,
    subject_type: str | None = None,
    severity: str | None = None,
    active: bool | None = None,
    db: Session = Depends(get_db),
    _: object = Depends(get_current_user),
):
    q = db.query(WatchlistEntry)
    if category:
        q = q.filter(WatchlistEntry.category == category)
    if subject_type:
        q = q.filter(WatchlistEntry.subject_type == subject_type)
    if severity:
        q = q.filter(WatchlistEntry.severity == severity)
    if active is not None:
        q = q.filter(WatchlistEntry.active.is_(active))
    return {"total": q.count(), "items": [serialize(w) for w in q.order_by(WatchlistEntry.id.desc()).all()]}


@router.post("", status_code=201)
def create_entry(payload: WatchlistCreate, db: Session = Depends(get_db),
                 _: object = Depends(get_current_user)):
    entry = WatchlistEntry(**payload.model_dump(), created_by="control-room")
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return serialize(entry)


@router.post("/bulk-import", status_code=201)
async def bulk_import(request: Request, db: Session = Depends(get_db),
                      _: object = Depends(get_current_user)):
    """Bulk import watchlist entries — JSON array/{"items": [...]} or CSV (plan §13).

    CSV columns: category,subject_type,identifier,severity,description,fir_number,police_station
    """
    content_type = request.headers.get("content-type", "")
    items: list[dict] = []

    if "csv" in content_type or "text/plain" in content_type:
        raw = (await request.body()).decode("utf-8-sig")
        items = [dict(r) for r in csv.DictReader(io.StringIO(raw))]
    else:
        try:
            payload = await request.json()
        except Exception:
            raise HTTPException(422, "Body must be JSON or CSV")
        if isinstance(payload, dict):
            items = payload.get("items", [])
        elif isinstance(payload, list):
            items = payload
        if not isinstance(items, list):
            raise HTTPException(422, "Expected a list of items or {\"items\": [...]}")

    valid_categories = {
        "stolen_vehicle", "wanted_vehicle", "blacklisted_vehicle", "watchlist_vehicle",
        "wanted_person", "missing_person", "suspect_person", "person_of_interest",
        "suspect", "vip",
    }
    created: list[str] = []
    skipped: list[dict] = []

    for i, raw_item in enumerate(items):
        if not isinstance(raw_item, dict):
            skipped.append({"index": i, "reason": "not an object"})
            continue
        identifier = str(raw_item.get("identifier") or raw_item.get("plate") or "").strip()
        if not identifier:
            skipped.append({"index": i, "reason": "missing identifier"})
            continue
        category = str(raw_item.get("category") or "stolen_vehicle").strip()
        if category not in valid_categories:
            category = "wanted_person" if "person" in category else "stolen_vehicle"
        subject_type = str(raw_item.get("subject_type") or "").strip()
        if subject_type not in {"vehicle", "person"}:
            subject_type = "person" if "person" in category else "vehicle"
        severity = str(raw_item.get("severity") or "medium").strip().lower()
        if severity not in {"critical", "high", "medium", "low"}:
            severity = "medium"

        exists = (
            db.query(WatchlistEntry)
            .filter(
                WatchlistEntry.identifier == identifier,
                WatchlistEntry.subject_type == subject_type,
            )
            .first()
        )
        if exists:
            skipped.append({"index": i, "identifier": identifier, "reason": "duplicate"})
            continue

        db.add(WatchlistEntry(
            category=category,
            subject_type=subject_type,
            identifier=identifier,
            description=raw_item.get("description"),
            severity=severity,
            fir_number=raw_item.get("fir_number") or None,
            police_station=raw_item.get("police_station") or None,
            active=bool(raw_item.get("active", True)),
            created_by="bulk-import",
        ))
        created.append(identifier)

    db.commit()
    return {
        "received": len(items),
        "created": len(created),
        "created_identifiers": created,
        "skipped": len(skipped),
        "skipped_details": skipped[:50],
    }


@router.patch("/{entry_id}")
def update_entry(entry_id: int, payload: WatchlistUpdate, db: Session = Depends(get_db),
                 _: object = Depends(get_current_user)):
    entry = db.get(WatchlistEntry, entry_id)
    if not entry:
        raise HTTPException(404, "Watchlist entry not found")
    for k, v in payload.model_dump(exclude_none=True).items():
        setattr(entry, k, v)
    db.commit()
    db.refresh(entry)
    return serialize(entry)


@router.delete("/{entry_id}", status_code=204)
def delete_entry(entry_id: int, db: Session = Depends(get_db),
                 _: object = Depends(get_current_user)):
    entry = db.get(WatchlistEntry, entry_id)
    if not entry:
        raise HTTPException(404, "Watchlist entry not found")
    db.delete(entry)
    db.commit()
