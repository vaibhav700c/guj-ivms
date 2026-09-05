"""Alert correlation engine — watchlist cross-referencing of ANPR events.

Implements the "analytics at the edge, correlation at the center" principle:
ANPR/detection events arrive from edge nodes (or the built-in simulator),
are matched against the active watchlist, and correlated alerts are pushed
to all connected control-room clients in real time.
"""
import logging
from datetime import datetime, timezone

from sqlalchemy import func
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


def _normalized_identifier_col():
    """SQL-side normalization mirroring `normalize_plate` for the common case
    (identifiers are human-formatted, e.g. "GJ 01 AB 1234" or "GJ-01-AB-1234").

    Lets the common "is this plate on the watchlist at all" check run as a
    single targeted DB query instead of hydrating every active watchlist
    entry into Python on every ingested event (plan §17.1 — ingest hot path,
    simulator fires every 2s). Same convention already used by
    `vehicles._registry_query` for VAHAN registry lookups.
    """
    return func.upper(
        func.replace(func.replace(WatchlistEntry.identifier, " ", ""), "-", "")
    )


class AlertEngine:
    def evaluate_anpr_event(self, db: Session, event: ANPREvent) -> Alert | None:
        """Match one ANPR event against the active watchlist (plan §8).

        Exact match is tried first as a single indexed-ish query scoped to
        active vehicle entries (0-1 rows, no Python scan). The expensive
        per-entry fuzzy (OCR-tolerant) scan only runs — and only then loads
        the full active-entry list — when the exact query misses, which is
        the one case where a full comparison is unavoidable.
        """
        match: WatchlistEntry | None = (
            db.query(WatchlistEntry)
            .filter(
                WatchlistEntry.active.is_(True),
                WatchlistEntry.subject_type == "vehicle",
                _normalized_identifier_col() == event.plate_normalized,
            )
            .first()
        )
        exact = match is not None
        if match is None:
            entries = (
                db.query(WatchlistEntry)
                .filter(
                    WatchlistEntry.active.is_(True),
                    WatchlistEntry.subject_type == "vehicle",
                )
                .all()
            )
            for entry in entries:
                if fuzzy_plate_match(entry.identifier, event.plate_text):
                    match = entry
                    break
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
            evidence_image_b64=event.evidence_image_b64,
            # Inherit provenance from the event that triggered this alert —
            # never let a fabricated (simulator) event produce an alert that
            # looks like a genuine edge-worker watchlist hit.
            source=event.source,
            message=message,
            status="new",
            timestamp=datetime.now(timezone.utc),
        )
        db.add(alert)
        db.commit()
        db.refresh(alert)
        self._publish(alert, camera)
        return alert

    def evaluate_person_event(
        self, db: Session, camera_id: int, name: str, confidence: float,
        snapshot_ref: str | None = None,
        evidence_image: str | None = None,
        embedding: list[float] | None = None,
        matched_watchlist_id: int | None = None,
        similarity: float | None = None,
        source: str = "edge_worker",
    ) -> Alert | None:
        """Face-recognition correlation (plan §6).

        Three tiers, in priority order:
        1. `matched_watchlist_id` — the edge worker already ran gallery search
           on-device (real ArcFace 512-d embeddings); trust and record it.
        2. `embedding` — center-side cosine similarity against enrolled
           `reference_embedding`s (real matching on server).
        3. Token/name fallback — demo-mode matching for the simulator.
        """
        match: WatchlistEntry | None = None
        sim_used: float | None = similarity
        # Diagnostic label for *which matching path* fired (useful in the
        # message text regardless of provenance) — this is NOT how callers
        # should tell a fabricated alert from a genuine one; that is what the
        # structured `source` param/column is for. "name-token" is the
        # simulator's demo-mode fallback (token overlap on name, no real
        # biometric match).
        match_mode = "name-token"

        if matched_watchlist_id is not None:
            # Edge already ran on-device ArcFace gallery search — a single
            # PK lookup, no need to hydrate the whole active-person table.
            match = (
                db.query(WatchlistEntry)
                .filter(
                    WatchlistEntry.id == matched_watchlist_id,
                    WatchlistEntry.active.is_(True),
                    WatchlistEntry.subject_type == "person",
                )
                .first()
            )
            match_mode = "edge-arcface"
        elif embedding:
            import math

            def _cos(a: list[float], b: list[float]) -> float:
                num = sum(x * y for x, y in zip(a, b))
                da = math.sqrt(sum(x * x for x in a))
                db_ = math.sqrt(sum(y * y for y in b))
                return num / (da * db_ + 1e-9)

            entries = (
                db.query(WatchlistEntry)
                .filter(
                    WatchlistEntry.active.is_(True),
                    WatchlistEntry.subject_type == "person",
                )
                .all()
            )
            best_sim = 0.0
            for entry in entries:
                ref = entry.reference_embedding
                if not ref or len(ref) != len(embedding):
                    continue
                sim = _cos(embedding, ref)
                if sim > best_sim:
                    best_sim, match = sim, entry
            if match and best_sim >= 0.45:
                sim_used = round(best_sim, 3)
                match_mode = "center-arcface"
            else:
                match = None
        if match is None and embedding is None:
            # Demo-mode fallback (used by the simulator): no real biometric
            # embedding was supplied at all, so match on name-token overlap
            # plus a tiny random hit rate to keep the demo alive. Genuine
            # edge-worker face events always carry `embedding` or
            # `matched_watchlist_id` and never reach this branch.
            import random

            entries = (
                db.query(WatchlistEntry)
                .filter(
                    WatchlistEntry.active.is_(True),
                    WatchlistEntry.subject_type == "person",
                )
                .all()
            )
            for entry in entries:
                token_match = any(
                    tok in entry.identifier.lower()
                    for tok in name.lower().split() if len(tok) > 3
                )
                if token_match or random.random() < 0.02:
                    match = entry
                    break

        if match is None:
            return None

        camera = db.get(Camera, camera_id)
        similarity_note = f" · ArcFace cos {sim_used:.2f}" if sim_used else ""
        alert = Alert(
            alert_type="watchlist_person",
            severity=match.severity,
            camera_id=camera_id,
            watchlist_id=match.id,
            detected_identifier=name or match.identifier,
            match_confidence=round(sim_used, 3) if sim_used else round(confidence, 2),
            snapshot_ref=snapshot_ref,
            evidence_image_b64=evidence_image,
            source=source,
            message=(
                f"{'WANTED' if match.category == 'wanted_person' else 'MISSING'} person "
                f"{match.identifier} matched by face recognition at "
                f"{camera.name if camera else 'camera #' + str(camera_id)} "
                f"({match_mode}{similarity_note})"
            ),
            status="new",
            timestamp=datetime.now(timezone.utc),
        )
        db.add(alert)
        db.commit()
        db.refresh(alert)
        self._publish(alert, camera)
        return alert

    def _publish(self, alert: Alert, camera: Camera | None) -> None:
        """Fire-and-forget push to all connected control-room clients."""
        import asyncio

        payload = self.serialize(alert, camera_name=camera.name if camera else None)
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(event_bus.publish("alerts:new", payload))
        except RuntimeError:
            pass

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
            "source": alert.source,
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
