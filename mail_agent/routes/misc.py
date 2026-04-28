"""
routes/misc.py

GET /health
GET /dashboard
GET /files/{file_id}
GET /skills
"""

import os
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from sqlalchemy import text

from mail_agent.agents._base import SKILLS
from mail_agent.database import SessionLocal
from mail_agent.models import ApplicantFile

router = APIRouter(tags=["misc"])


@router.get("/health")
def health_check():
    try:
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
        return {
            "status": "healthy",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "skills_loaded": len(SKILLS),
        }
    except Exception as exc:
        return JSONResponse(
            status_code=503, content={"status": "unhealthy", "error": str(exc)}
        )


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    html_path = os.path.join(os.path.dirname(__file__), "..", "static", "dashboard.html")
    with open(html_path) as fh:
        return fh.read()


@router.get("/files/{file_id}")
def get_file(file_id: int):
    db = SessionLocal()
    rec = db.query(ApplicantFile).filter(ApplicantFile.id == file_id).first()
    db.close()
    if not rec:
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(
        path=rec.file_path,
        filename=rec.original_filename,
        media_type="application/octet-stream",
    )


@router.get("/skills")
def list_skills():
    return {
        name: {"description": s["description"], "execution_mode": s["execution_mode"]}
        for name, s in SKILLS.items()
    }