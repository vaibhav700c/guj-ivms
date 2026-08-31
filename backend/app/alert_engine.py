"""Alert correlation engine — watchlist cross-referencing of ANPR events.

Implements the "analytics at the edge, correlation at the center" principle:
ANPR/detection events arrive from edge nodes (or the built-in simulator),
are matched against the active watchlist, and correlated alerts are pushed
to all connected control-room clients in real time.
"""
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.eventbus import event_bus
from app.models import ANPREvent, Alert, Camera, WatchlistEntry

logger = logging.getLogger(__name__)


def normalize_plate(plate: str) -> str:
    """Normalize Indian plate text: uppercase, strip separators/spaces."""
    return "".join(ch for ch in plate.upper() if ch.isalnum())


def fuzzy_plate_match(a: str, b: str, threshold: float = 0.85) -> bool:
    """OCR-tolerant similarity using SequenceMatcher (handles 0/O, I/1 misses)."""
    from difflib import SequenceMatcher

    a, b = normalize_plate(a), normalize_plate(b)
    if a == b:
        return True
    return SequenceMatcher(None, a, b).ratio() >= threshold


class AlertEngine:
    def evaluate_anpr_event(self, db: Session, event: ANPREvent) -> Alert | None:
        """Match one ANPR event against the active watchlist."""
        entries = (
            db.query(WatchlistEntry)
            .filter(
                WatchlistEntry.active.is_(True),
                WatchlistEntry.subject_type == "vehicle",
            )
            .all()
        )
        match: WatchlistEntry | None = None
        exact = False
        for entry in entries:
            if normalize_plate(entry.identifier) == event.plate_normalized:
                match, exact = entry, True
                break
            if fuzzy_plate_match(entry.identifier, event.plate_text):
                match = entry  # probable match — keep scanning for exact
        if match is None:
            return None

        camera = db.get(Camera, event.camera_id)
        alert_type = (
            "watchlist_vehicle" if match.category == "stolen_vehicle" else "blacklist_vehicle"
        )
        confidence = event.confidence if exact else round(event.confidence * 0.85, 2)
        message = (
            f"{'STOLEN' if match.category == 'stolen_vehicle' else 'BLACKLISTED'} vehicle "
            f"{event.plate_text} detected at {camera.name if camera else 'camera #' + str(event.camera_id)}"
            f"{'' if exact else ' (probable OCR match)'}"
        )
        alert = Alert(
            alert_type=alert_type,
            severity=match.severity,
            camera_id=event.camera_id,
            watchlist_id=match.id,
            detected_identifier=event.plate_text,
            match_confidence=confidence,
            snapshot_ref=event.snapshot_ref,
            message=message,
            status="new",
            timestamp=datetime.now(timezone.utc),
        )
        db.add(alert)
        db.commit()
        db.refresh(alert)

        payload = self.serialize(alert, camera_name=camera.name if camera else None)
        # fire-and-forget push to WS clients
        import asyncio

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(event_bus.publish("alerts:new", payload))
        except RuntimeError:
            pass
        return alert

    @staticmethod
    def serialize(alert: Alert, camera_name: str | None = None) -> dict:
        return {
            "id": alert.id,
            "alert_type": alert.alert_type,
            "severity": alert.severity,
            "camera_id": alert.camera_id,
            "camera_name": camera_name
            or (alert.camera.name if alert.camera else None),
            "detected_identifier": alert.detected_identifier,
            "match_confidence": alert.match_confidence,
            "message": alert.message,
            "status": alert.status,
            "timestamp": alert.timestamp.isoformat() if alert.timestamp else None,
            "snapshot_ref": alert.snapshot_ref,
            "watchlist": {
                "id": alert.watchlist.id,
                "category": alert.watchlist.category,
                "fir_number": alert.watchlist.fir_number,
                "police_station": alert.watchlist.police_station,
            }
            if alert.watchlist
            else None,
        }


alert_engine = AlertEngine()
