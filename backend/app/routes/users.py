"""User management + RBAC (plan §13 /users)."""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.audit import write_audit
from app.db import get_db
from app.models import User
from app.security import Permission, hash_password, require_permission

router = APIRouter(prefix="/users", tags=["users"])


class UserCreate(BaseModel):
    username: str
    password: str
    email: str | None = None
    full_name: str | None = None
    role: str = "operator"  # admin | operator | analyst | viewer
    department: str | None = None


@router.get("")
def list_users(db: Session = Depends(get_db),
              _: object = Depends(require_permission(Permission.USER_MANAGE))):
    return {"total": db.query(User).count(), "items": [
        {"id": u.id, "username": u.username, "email": u.email,
         "full_name": u.full_name, "role": u.role, "department": u.department,
         "active": u.active}
        for u in db.query(User).all()
    ]}


@router.post("", status_code=201)
def create_user(payload: UserCreate, request: Request, db: Session = Depends(get_db),
                actor: User | None = Depends(require_permission(Permission.USER_MANAGE))):
    if payload.role not in {"admin", "operator", "analyst", "viewer"}:
        raise HTTPException(422, "Invalid role")
    if db.query(User).filter(User.username == payload.username).first():
        raise HTTPException(409, "Username already exists")
    user = User(
        username=payload.username,
        email=payload.email,
        full_name=payload.full_name,
        hashed_password=hash_password(payload.password),
        role=payload.role,
        department=payload.department,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    write_audit(db, actor=actor, action="user.create", target_type="user",
                target_id=user.id, detail={"username": user.username, "role": user.role},
                request=request)
    return {"id": user.id, "username": user.username, "role": user.role}


@router.patch("/{user_id}")
def toggle_user(user_id: int, active: bool, request: Request, db: Session = Depends(get_db),
                actor: User | None = Depends(require_permission(Permission.USER_MANAGE))):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    user.active = active
    db.commit()
    write_audit(db, actor=actor, action="user.update", target_type="user",
                target_id=user.id, detail={"active": active}, request=request)
    return {"id": user.id, "username": user.username, "active": user.active}
