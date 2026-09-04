"""Authentication — JWT tokens + PBKDF2 password hashing (stdlib, no native deps).

Also implements RBAC (plan §17.2): a `Permission` enum, a `ROLE_PERMISSIONS` map,
and a `require_permission()` dependency factory. The roles that actually exist
(created by app/seed.py) are `admin`, `operator`, `analyst`; the frontend's demo
path uses `viewer`. The plan's `super_admin`/`dept_admin` map onto `admin`;
anything unknown/missing is treated as the least-privileged `viewer`.
"""
import hashlib
import os
from datetime import datetime, timedelta, timezone
from enum import Enum

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import User

_bearer = HTTPBearer(auto_error=False)

# ---------- password hashing (PBKDF2-SHA256, 390k iterations) ----------


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 390_000)
    return f"pbkdf2_sha256$390000${salt.hex()}${dk.hex()}"


def verify_password(password: str, hashed: str) -> bool:
    try:
        _, iters, salt_hex, dk_hex = hashed.split("$")
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), int(iters)
        )
        return dk.hex() == dk_hex
    except Exception:
        return False


# ---------- JWT ----------


def create_access_token(user: User) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    payload = {
        "sub": user.username,
        "role": user.role,
        "uid": user.id,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired"
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        )


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User | None:
    """Returns the authenticated user, or None when auth is disabled/demo mode."""
    if not settings.REQUIRE_AUTH:
        return None
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
        )
    payload = decode_token(credentials.credentials)
    user = db.query(User).filter(User.username == payload.get("sub")).first()
    if user is None or not user.active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found"
        )
    return user


def require_roles(*roles: str):
    """Dependency factory — restrict endpoint to given roles (when auth enabled)."""

    def _checker(user: User | None = Depends(get_current_user)) -> User | None:
        if settings.REQUIRE_AUTH and user is not None and user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions"
            )
        return user

    return _checker


# ---------- RBAC (plan §17.2) ----------


class Permission(str, Enum):
    CAMERA_VIEW = "camera:view"
    CAMERA_MANAGE = "camera:manage"
    FEED_VIEW = "feed:view"
    ANALYTICS_VIEW = "analytics:view"
    WATCHLIST_VIEW = "watchlist:view"
    WATCHLIST_MANAGE = "watchlist:manage"
    ALERT_VIEW = "alert:view"
    ALERT_MANAGE = "alert:manage"
    USER_MANAGE = "user:manage"
    SYSTEM_CONFIG = "system:config"


# Maps onto the roles that actually exist (app/seed.py: admin, operator, analyst)
# plus the frontend demo-mode role `viewer`. `admin` == plan's super_admin/dept_admin
# (this deployment has no per-department scoping, so admin is state-level + full).
ROLE_PERMISSIONS: dict[str, list[Permission]] = {
    "admin": list(Permission),
    "operator": [
        Permission.CAMERA_VIEW,
        Permission.FEED_VIEW,
        Permission.ANALYTICS_VIEW,
        Permission.WATCHLIST_VIEW,
        Permission.WATCHLIST_MANAGE,
        Permission.ALERT_VIEW,
        Permission.ALERT_MANAGE,
    ],
    "analyst": [
        Permission.CAMERA_VIEW,
        Permission.FEED_VIEW,
        Permission.ANALYTICS_VIEW,
        Permission.WATCHLIST_VIEW,
        Permission.ALERT_VIEW,
    ],
    "viewer": [
        Permission.CAMERA_VIEW,
        Permission.FEED_VIEW,
        Permission.ANALYTICS_VIEW,
    ],
}


def require_permission(permission: Permission):
    """Dependency factory — restrict endpoint to roles holding `permission`.

    No-op when auth is disabled (demo mode): mirrors `require_roles` by only
    enforcing `settings.REQUIRE_AUTH and user is not None`. An unknown/missing
    role is treated as `viewer` (least-privileged), never as unrestricted.
    """

    def _checker(user: User | None = Depends(get_current_user)) -> User | None:
        if settings.REQUIRE_AUTH and user is not None:
            allowed = ROLE_PERMISSIONS.get(user.role, ROLE_PERMISSIONS["viewer"])
            if permission not in allowed:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions"
                )
        return user

    return _checker
