"""Watchlist routes — CRUD for stolen/blacklisted vehicles & wanted persons."""
from fastapi import APIRouter, Depends, HTTPException
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
