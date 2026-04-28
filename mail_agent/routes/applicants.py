"""
routes/applicants.py

GET /applicants
GET /applicants/{thread_id}
"""

from fastapi import APIRouter, HTTPException
from mail_agent.database import SessionLocal
from mail_agent.models import ApplicantState

router = APIRouter(prefix="/applicants", tags=["applicants"])


@router.get("")
def list_applicants(status: str | None = None):
    db = SessionLocal()
    try:
        query = db.query(ApplicantState)
        if status:
            query = query.filter(ApplicantState.status == status)
        applicants = query.order_by(ApplicantState.updated_at.desc()).all()
        return {
            "applicants": [
                {
                    "thread_id": a.thread_id,
                    "candidate_email": a.candidate_email,
                    "status": a.status,
                    "extracted_data": a.extracted_data,
                    "missing_fields": a.missing_fields,
                    "reply_count": a.reply_count,
                    "created_at": a.created_at.isoformat() if a.created_at else None,
                    "updated_at": a.updated_at.isoformat() if a.updated_at else None,
                    "approved_at": a.approved_at.isoformat() if a.approved_at else None,
                }
                for a in applicants
            ],
            "total": len(applicants),
        }
    finally:
        db.close()


@router.get("/{thread_id}")
def get_applicant(thread_id: str):
    db = SessionLocal()
    try:
        state = db.query(ApplicantState).filter(
            ApplicantState.thread_id == thread_id
        ).first()
        if not state:
            raise HTTPException(status_code=404, detail="Thread not found")
        return {
            "thread_id": state.thread_id,
            "candidate_email": state.candidate_email,
            "status": state.status,
            "extracted_data": state.extracted_data,
            "missing_fields": state.missing_fields,
            "reply_count": state.reply_count,
            "created_at": state.created_at.isoformat() if state.created_at else None,
            "updated_at": state.updated_at.isoformat() if state.updated_at else None,
            "approved_at": state.approved_at.isoformat() if state.approved_at else None,
        }
    finally:
        db.close()