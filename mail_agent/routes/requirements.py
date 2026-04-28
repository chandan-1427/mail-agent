"""
routes/requirements.py

POST   /requirements/{inbox_id}
PUT    /requirements/{inbox_id}
GET    /requirements/{inbox_id}
DELETE /requirements/{inbox_id}
"""

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from mail_agent.database import SessionLocal
from mail_agent.models import JobRequirement
from mail_agent.schemas import RequirementCreate
from mail_agent.utils import validate_requirements, get_requirements

router = APIRouter(prefix="/requirements", tags=["requirements"])


@router.post("/{inbox_id}")
def create_requirements(inbox_id: str, payload: RequirementCreate):
    fields = [f.model_dump() for f in payload.required_fields]
    if errors := validate_requirements(fields):
        raise HTTPException(status_code=422, detail={"validation_errors": errors})
    db = SessionLocal()
    try:
        if db.query(JobRequirement).filter(JobRequirement.inbox_id == inbox_id).first():
            raise HTTPException(status_code=409, detail="Requirements exist. Use PUT to update.")
        db.add(JobRequirement(inbox_id=inbox_id, required_fields=fields))
        db.commit()
        return {"status": "created", "inbox_id": inbox_id, "field_count": len(fields)}
    finally:
        db.close()


@router.put("/{inbox_id}")
def update_requirements(inbox_id: str, payload: RequirementCreate):
    fields = [f.model_dump() for f in payload.required_fields]
    if errors := validate_requirements(fields):
        raise HTTPException(status_code=422, detail={"validation_errors": errors})
    db = SessionLocal()
    try:
        existing = db.query(JobRequirement).filter(
            JobRequirement.inbox_id == inbox_id
        ).first()
        if not existing:
            existing = JobRequirement(inbox_id=inbox_id)
            db.add(existing)
        existing.required_fields = fields
        existing.updated_at = datetime.now(timezone.utc)
        db.commit()
        return {"status": "updated", "inbox_id": inbox_id, "field_count": len(fields)}
    finally:
        db.close()


@router.get("/{inbox_id}")
def get_requirements_route(inbox_id: str):
    db = SessionLocal()
    try:
        reqs = get_requirements(db, inbox_id)
        is_custom = (
            db.query(JobRequirement)
            .filter(JobRequirement.inbox_id == inbox_id)
            .first() is not None
        )
        return {
            "inbox_id": inbox_id,
            "is_custom": is_custom,
            "required_fields": reqs,
            "field_count": len(reqs),
        }
    finally:
        db.close()


@router.delete("/{inbox_id}")
def delete_requirements(inbox_id: str):
    db = SessionLocal()
    try:
        existing = db.query(JobRequirement).filter(
            JobRequirement.inbox_id == inbox_id
        ).first()
        if not existing:
            raise HTTPException(status_code=404, detail="No custom requirements found")
        db.delete(existing)
        db.commit()
        return {"status": "deleted", "inbox_id": inbox_id}
    finally:
        db.close()