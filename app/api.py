"""
FastAPI routes and endpoints.
"""
import os
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from sqlalchemy import text

from .database import SessionLocal, ApplicantState, ApplicantMessageLog, ApplicantFile, JobRequirement
from .schemas import RequirementCreate
from .requirements import get_requirements_for_inbox, get_field_names, validate_requirements, DEFAULT_REQUIREMENTS
from .security import check_rate_limit, detect_spam, verify_webhook_signature, check_candidate_history
from .orchestrator import process_webhook_background, get_spam_tools
from .config import AGENTMAIL_API_KEY, OPENROUTER_API_KEY, INBOX_ID

# ============================================================
# FASTAPI APP
# ============================================================
app = FastAPI(title="HR Triage Agent — Dynamic Skills Architecture")


# ============================================================
# DASHBOARD
# ============================================================

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    """Serve the admin dashboard."""
    html_path = os.path.join(os.path.dirname(__file__), "static", "dashboard.html")
    with open(html_path, "r", encoding="utf-8") as f:
        return f.read()


# ============================================================
# HEALTH CHECK
# ============================================================

@app.get("/health")
def health_check(request: Request):
    """Health check endpoint for monitoring."""
    try:
        db = SessionLocal()
        # Test database connection
        db.execute(text("SELECT 1"))
        db.close()
        
        skills = request.app.state.skills if hasattr(request.app.state, 'skills') else {}
        
        return JSONResponse({
            "status": "healthy",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "services": {
                "database": "connected",
                "agentmail": "configured" if AGENTMAIL_API_KEY else "missing",
                "openrouter": "configured" if OPENROUTER_API_KEY else "missing",
            },
            "skills_loaded": len(skills),
        })
    except Exception as e:
        return JSONResponse(
            status_code=503,
            content={
                "status": "unhealthy",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "error": str(e),
            }
        )


# ============================================================
# WEBHOOK
# ============================================================

@app.post("/")
async def handle_agentmail_webhook(request: Request, background_tasks: BackgroundTasks):
    """Handle incoming AgentMail webhooks."""
    import logging
    logger = logging.getLogger(__name__)
    
    agents = request.app.state.agents
    tracer = request.app.state.tracer
    
    # Get raw body for signature verification
    body_bytes = await request.body()
    payload_str = body_bytes.decode('utf-8')
    
    # Webhook signature verification
    signature = request.headers.get("X-Webhook-Signature", "")
    if signature and not verify_webhook_signature(payload_str, signature):
        logger.warning("Invalid webhook signature")
        return JSONResponse(
            status_code=401,
            content={"status": "invalid_signature", "message": "Invalid webhook signature"}
        )
    
    try:
        payload = await request.json()
    except Exception as e:
        logger.error(f"Failed to parse JSON: {e}")
        return JSONResponse(
            status_code=400,
            content={"status": "invalid_json", "message": "Invalid JSON payload"}
        )
    
    if payload.get("event_type") != "message.received":
        return {"status": "ignored"}

    message_data = payload.get("message", {})
    sender = message_data.get("from_", "")
    thread_id = message_data.get("thread_id")
    inbox_id = message_data.get("inbox_id")
    message_id = message_data.get("message_id")
    raw_text = message_data.get("text", "")
    attachments = message_data.get("attachments", [])

    # Rate limiting check
    if not check_rate_limit(sender):
        logger.warning(f"Rate limit blocked: {sender}")
        return JSONResponse(
            status_code=429,
            content={"status": "rate_limited", "message": "Too many requests"}
        )

    # Spam detection
    is_spam, spam_reason = detect_spam(raw_text, sender, retain_memory_func=lambda content: get_spam_tools().retain_memory(run_context=None, content=content))
    if is_spam:
        logger.warning(f"Spam detected from {sender}: {spam_reason}")
        return {"status": "spam_rejected", "reason": spam_reason}

    db = SessionLocal()
    db.add(ApplicantMessageLog(
        thread_id=thread_id, sender_email=sender,
        message_id=message_id, raw_text=raw_text,
    ))

    if INBOX_ID and INBOX_ID in sender:
        print("🔁 Self-sent — ignoring.")
        db.commit()
        db.close()
        return {"status": "ignored"}

    db.commit()
    db.close()

    is_known_spammer, spam_reason = check_candidate_history(sender, recall_memory_func=lambda query: get_spam_tools().recall_memory(run_context=None, query=query))
    if is_known_spammer:
        logger.warning(f"Known bad actor blocked: {sender}")
        return {"status": "blocked", "reason": spam_reason}

    # Queue background processing
    background_tasks.add_task(
        process_webhook_background,
        sender=sender, thread_id=thread_id, inbox_id=inbox_id,
        message_id=message_id, raw_text=raw_text, attachments=attachments,
        agents=agents, tracer=tracer,
    )

    return {"status": "queued", "thread_id": thread_id}


# ============================================================
# APPLICANTS API
# ============================================================

@app.get("/applicants")
def list_applicants(status: str | None = None):
    """List all applicants, optionally filtered by status."""
    db = SessionLocal()
    try:
        query = db.query(ApplicantState)
        if status:
            query = query.filter(ApplicantState.status == status)
        query = query.order_by(ApplicantState.updated_at.desc())
        applicants = query.all()
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


@app.get("/applicants/{thread_id}")
def get_applicant_state(thread_id: str):
    """Get a single applicant's state."""
    db = SessionLocal()
    try:
        state = db.query(ApplicantState).filter(ApplicantState.thread_id == thread_id).first()
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


# ============================================================
# REQUIREMENTS API
# ============================================================

@app.post("/requirements/{inbox_id}")
def create_requirements(inbox_id: str, payload: RequirementCreate):
    """Create custom requirements for an inbox."""
    fields_dicts = [f.model_dump() for f in payload.required_fields]
    errors = validate_requirements(fields_dicts)
    if errors:
        raise HTTPException(status_code=422, detail={"validation_errors": errors})
    db = SessionLocal()
    try:
        if db.query(JobRequirement).filter(JobRequirement.inbox_id == inbox_id).first():
            raise HTTPException(status_code=409, detail=f"Requirements exist for '{inbox_id}'. Use PUT to update.")
        job_req = JobRequirement(inbox_id=inbox_id, required_fields=fields_dicts)
        db.add(job_req)
        db.commit()
        db.refresh(job_req)
        return {"status": "created", "inbox_id": inbox_id, "required_fields": job_req.required_fields, "field_count": len(job_req.required_fields)}
    finally:
        db.close()


@app.put("/requirements/{inbox_id}")
def update_requirements(inbox_id: str, payload: RequirementCreate):
    """Update requirements for an inbox."""
    fields_dicts = [f.model_dump() for f in payload.required_fields]
    errors = validate_requirements(fields_dicts)
    if errors:
        raise HTTPException(status_code=422, detail={"validation_errors": errors})
    db = SessionLocal()
    try:
        existing = db.query(JobRequirement).filter(JobRequirement.inbox_id == inbox_id).first()
        if not existing:
            existing = JobRequirement(inbox_id=inbox_id)
            db.add(existing)
        existing.required_fields = fields_dicts
        existing.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(existing)
        return {"status": "updated", "inbox_id": inbox_id, "required_fields": existing.required_fields, "field_count": len(existing.required_fields)}
    finally:
        db.close()


@app.get("/requirements/{inbox_id}")
def get_requirements(inbox_id: str):
    """Get requirements for an inbox."""
    db = SessionLocal()
    try:
        requirements = get_requirements_for_inbox(db, inbox_id)
        job_req = db.query(JobRequirement).filter(JobRequirement.inbox_id == inbox_id).first()
        return {
            "inbox_id": inbox_id,
            "is_custom": job_req is not None,
            "required_fields": requirements,
            "field_names": get_field_names(requirements),
            "field_count": len(requirements),
        }
    finally:
        db.close()


@app.delete("/requirements/{inbox_id}")
def delete_requirements(inbox_id: str):
    """Delete custom requirements for an inbox (reverts to defaults)."""
    db = SessionLocal()
    try:
        existing = db.query(JobRequirement).filter(JobRequirement.inbox_id == inbox_id).first()
        if not existing:
            raise HTTPException(status_code=404, detail=f"No custom requirements for '{inbox_id}'")
        db.delete(existing)
        db.commit()
        return {"status": "deleted", "inbox_id": inbox_id, "reverted_to": DEFAULT_REQUIREMENTS}
    finally:
        db.close()


# ============================================================
# FILES API
# ============================================================

@app.get("/files/{file_id}")
def get_file(file_id: int):
    """Get a file by ID."""
    db = SessionLocal()
    file_record = db.query(ApplicantFile).filter(ApplicantFile.id == file_id).first()
    db.close()
    if not file_record:
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path=file_record.file_path, filename=file_record.original_filename, media_type="application/octet-stream")


# ============================================================
# DEBUG ENDPOINTS
# ============================================================

@app.get("/skills")
def list_skills(request: Request):
    """List all loaded skills."""
    skills = request.app.state.skills
    return {
        name: {
            "description": s["description"],
            "execution_mode": s["execution_mode"],
            "license": s["license"],
            "metadata": s["metadata"],
            "source_file": s["source_file"],
        }
        for name, s in skills.items()
    }
