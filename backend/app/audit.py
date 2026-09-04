"""Audit & compliance trail helper (plan §17.1 Layer 4).

`write_audit()` is called from mutating routes to record who did what, to what,
and when. It is deliberately defensive: a logging failure must NEVER break the
underlying request, so every error is swallowed after a best-effort rollback.
"""
from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from app.models import AuditLog, User


def _client_ip(request: Request | None) -> str | None:
    if request is None:
        return None
    try:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else None
    except Exception:
        return None


def write_audit(
    db: Session,
    *,
    actor: User | None,
    action: str,
    target_type: str | None = None,
    target_id: Any = None,
    detail: dict | None = None,
    request: Request | None = None,
    fallback_actor: str = "control-room",
) -> None:
    """Insert one audit row. Best-effort — never raises.

    `actor` is the authenticated User (or None in demo mode, in which case
    `fallback_actor` — e.g. "control-room" / "bulk-import" / "anonymous" — is
    recorded instead, matching the existing demo-mode attribution strings).
    """
    try:
        entry = AuditLog(
            actor=actor.username if actor is not None else fallback_actor,
            actor_role=actor.role if actor is not None else None,
            action=action,
            target_type=target_type,
            target_id=str(target_id) if target_id is not None else None,
            detail=detail or {},
            ip_address=_client_ip(request),
        )
        db.add(entry)
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
