"""Department management (plan §13 /departments)."""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.audit import write_audit
from app.db import get_db
from app.models import Camera, Department, User
from app.security import Permission, require_permission

router = APIRouter(prefix="/departments", tags=["departments"])


class DepartmentCreate(BaseModel):
    name: str
    code: str
    description: str | None = None
    contact: dict = {}


@router.get("")
def list_departments(db: Session = Depends(get_db)):
    out = []
    for d in db.query(Department).all():
        cam_count = db.query(Camera).filter(Camera.department_id == d.id).count()
        out.append({
            "id": d.id, "name": d.name, "code": d.code,
            "description": d.description, "contact": d.contact,
            "cameras": cam_count,
        })
    return {"total": len(out), "items": out}


@router.post("", status_code=201)
def create_department(payload: DepartmentCreate, request: Request, db: Session = Depends(get_db),
                      user: User | None = Depends(require_permission(Permission.SYSTEM_CONFIG))):
    dept = Department(**payload.model_dump())
    db.add(dept)
    db.commit()
    db.refresh(dept)
    write_audit(db, actor=user, action="department.create", target_type="department",
                target_id=dept.id, detail={"name": dept.name, "code": dept.code}, request=request)
    return {"id": dept.id, "name": dept.name, "code": dept.code}


@router.get("/{dept_id}")
def get_department(dept_id: int, db: Session = Depends(get_db)):
    dept = db.get(Department, dept_id)
    if not dept:
        raise HTTPException(404, "Department not found")
    cams = db.query(Camera).filter(Camera.department_id == dept.id).all()
    return {
        "id": dept.id, "name": dept.name, "code": dept.code,
        "description": dept.description, "contact": dept.contact,
        "cameras": [
            {"id": c.id, "name": c.name, "status": c.status,
             "analytics_tier": c.analytics_tier}
            for c in cams
        ],
    }
