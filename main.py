import os
import uvicorn
import json
from datetime import datetime, timezone
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

# Database imports
from sqlalchemy import Integer, create_engine, Column, String, JSON, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agentmail import AgentMail

# Skills loader
from skills_loader import load_skills, get_skill_content

load_dotenv()

# ============================================================
# 1. ENVIRONMENT & DATABASE
# ============================================================
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")
AGENTMAIL_API_KEY = os.getenv("AGENTMAIL_API_KEY")
INBOX_ID = os.getenv("INBOX_ID")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

UPLOAD_DIR = "uploads"
RESUME_DIR = os.path.join(UPLOAD_DIR, "resumes")
COVER_LETTER_DIR = os.path.join(UPLOAD_DIR, "cover_letters")
OTHER_DIR = os.path.join(UPLOAD_DIR, "other")

os.makedirs(RESUME_DIR, exist_ok=True)
os.makedirs(COVER_LETTER_DIR, exist_ok=True)
os.makedirs(OTHER_DIR, exist_ok=True)


# ============================================================
# 2. DATABASE MODELS
# ============================================================
class ApplicantState(Base):
    __tablename__ = "applicant_triage"
    id = Column(Integer, primary_key=True, autoincrement=True)
    thread_id = Column(String, unique=True, index=True, nullable=False)
    candidate_email = Column(String, index=True, nullable=False)
    status = Column(String, default="PENDING", nullable=False)
    extracted_data = Column(JSON, default=dict)
    missing_fields = Column(JSON, default=list)
    latest_message = Column(String)
    reply_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    approved_at = Column(DateTime, nullable=True)


class ApplicantMessageLog(Base):
    __tablename__ = "applicant_message_log"
    id = Column(Integer, primary_key=True, autoincrement=True)
    thread_id = Column(String, index=True)
    sender_email = Column(String)
    message_id = Column(String)
    raw_text = Column(String)
    received_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class ApplicantFile(Base):
    __tablename__ = "applicant_files"
    id = Column(Integer, primary_key=True, autoincrement=True)
    thread_id = Column(String, index=True, nullable=False)
    candidate_email = Column(String, nullable=False)
    message_id = Column(String, nullable=False)
    file_type = Column(String, nullable=False)
    original_filename = Column(String, nullable=False)
    stored_filename = Column(String, nullable=False)
    file_path = Column(String, nullable=False)
    uploaded_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class JobRequirement(Base):
    __tablename__ = "job_requirements"
    id = Column(Integer, primary_key=True, autoincrement=True)
    inbox_id = Column(String, unique=True, index=True, nullable=False)
    required_fields = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class ApplicantStateHistory(Base):
    __tablename__ = "applicant_state_history"
    id = Column(Integer, primary_key=True, autoincrement=True)
    thread_id = Column(String, index=True, nullable=False)
    old_status = Column(String)
    new_status = Column(String)
    old_missing_fields = Column(JSON)
    new_missing_fields = Column(JSON)
    changed_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


Base.metadata.create_all(bind=engine)


# ============================================================
# 3. PYDANTIC SCHEMAS
# ============================================================

class FieldDefinition(BaseModel):
    name: str = Field(description="Lowercase, no spaces. e.g. 'linkedin', 'years_experience'")
    description: str = Field(description="Human-readable description. e.g. 'Your LinkedIn profile URL'")
    field_type: str = Field(description="One of: url, file, text, email, phone")


class RequirementCreate(BaseModel):
    required_fields: list[FieldDefinition] = Field(min_length=1)


class TriageResult(BaseModel):
    is_approved: bool
    extracted_data: dict
    missing_fields: list[str]
    reply_draft: str | None


# ============================================================
# 4. REQUIREMENT MANAGER (deterministic skill)
# ============================================================

VALID_FIELD_TYPES = {"url", "file", "text", "email", "phone"}

DEFAULT_REQUIREMENTS = [
    {"name": "linkedin", "description": "Your LinkedIn profile URL", "field_type": "url"},
    {"name": "github", "description": "Your GitHub profile URL", "field_type": "url"},
    {"name": "resume", "description": "Your resume as a file attachment or link", "field_type": "file"},
]


def validate_field(field: dict) -> list[str]:
    errors = []
    name = field.get("name", "")
    if not name or not isinstance(name, str):
        errors.append("Field 'name' is required and must be a non-empty string")
    elif " " in name or name != name.lower():
        errors.append(f"Field name '{name}' must be lowercase with no spaces (use underscores)")
    if not field.get("description"):
        errors.append(f"Field '{name}' must have a description")
    ft = field.get("field_type", "")
    if ft not in VALID_FIELD_TYPES:
        errors.append(f"Field '{name}' has invalid type '{ft}'. Must be one of: {VALID_FIELD_TYPES}")
    return errors


def validate_requirements(fields: list[dict]) -> list[str]:
    if not fields:
        return ["At least one required field must be specified"]
    all_errors = []
    seen_names = set()
    for field in fields:
        all_errors.extend(validate_field(field))
        name = field.get("name", "")
        if name in seen_names:
            all_errors.append(f"Duplicate field name: '{name}'")
        seen_names.add(name)
    return all_errors


def get_requirements_for_inbox(db, inbox_id: str) -> list[dict]:
    job_req = db.query(JobRequirement).filter(JobRequirement.inbox_id == inbox_id).first()
    if job_req and job_req.required_fields:
        return job_req.required_fields
    return DEFAULT_REQUIREMENTS


def get_field_names(requirements: list[dict]) -> list[str]:
    return [f["name"] for f in requirements]


# ============================================================
# 5. LOAD SKILLS
# ============================================================
print("\n📚 Loading skills...")
SKILLS = load_skills()
print(f"   Loaded {len(SKILLS)} skills total\n")


# ============================================================
# 6. SKILL-POWERED AGENTS
# ============================================================

def _make_model():
    return OpenAIChat(
        id="openai/gpt-4o",
        api_key=OPENROUTER_API_KEY,
        base_url="https://openrouter.ai/api/v1",
    )


def build_skill_agent(skill_name: str, agent_name: str | None = None) -> Agent:
    skill_content = get_skill_content(SKILLS, skill_name)
    return Agent(
        name=agent_name or skill_name,
        model=_make_model(),
        description=SKILLS[skill_name]["description"],
        instructions=[
            f"You are executing the '{skill_name}' skill. Follow these instructions exactly:",
            "",
            skill_content,
            "",
            "CRITICAL: Return ONLY raw JSON as specified in the Output Format section.",
            "Do NOT wrap your response in markdown code fences.",
            "Do NOT include any text before or after the JSON.",
        ],
        markdown=False,
    )


email_parser_agent = build_skill_agent("email-parser", "Email Parser")
triage_agent = build_skill_agent("application-triage", "Triage Decision Agent")
reply_composer_agent = build_skill_agent("hr-reply-composer", "Reply Composer")

print("🤖 Skill-powered agents built\n")


# ============================================================
# 7. DETERMINISTIC ATTACHMENT HANDLER
# ============================================================

agentmail_client = AgentMail(api_key=AGENTMAIL_API_KEY)


def attachment_handler(attachments, thread_id, sender, inbox_id, message_id, db):
    saved_files = {}
    for attachment in attachments:
        original_filename = attachment.get("filename")
        attachment_id = attachment.get("attachment_id")
        if not original_filename or not attachment_id:
            continue
        lower_filename = original_filename.lower()
        if any(kw in lower_filename for kw in ["resume", "cv"]):
            file_type, save_dir = "resume", RESUME_DIR
        elif "cover" in lower_filename:
            file_type, save_dir = "cover_letter", COVER_LETTER_DIR
        else:
            file_type, save_dir = "other", OTHER_DIR
        stored_filename = f"{thread_id}_{attachment_id}_{original_filename}"
        file_path = os.path.join(save_dir, stored_filename)
        saved_files[file_type] = file_path
        try:
            attachment_response = agentmail_client.inboxes.messages.get_attachment(
                inbox_id=inbox_id, message_id=message_id, attachment_id=attachment_id,
            )
            download_url = getattr(attachment_response, "download_url", None)
            if not download_url and isinstance(attachment_response, dict):
                download_url = attachment_response.get("download_url")
            if download_url:
                import urllib.request
                with urllib.request.urlopen(download_url) as response:
                    file_bytes = response.read()
                with open(file_path, "wb") as f:
                    f.write(file_bytes)
                db.add(ApplicantFile(
                    thread_id=thread_id, candidate_email=sender, message_id=message_id,
                    file_type=file_type, original_filename=original_filename,
                    stored_filename=stored_filename, file_path=file_path,
                ))
        except Exception as e:
            print(f"  ⚠️ Failed to save attachment {original_filename}: {e}")
    return saved_files


# ============================================================
# 8. JSON PARSER
# ============================================================

def _parse_agent_json(raw_content: str) -> dict:
    cleaned = raw_content.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned.replace("```json", "", 1)
    if cleaned.startswith("```"):
        cleaned = cleaned.replace("```", "", 1)
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    return json.loads(cleaned.strip())


# ============================================================
# 9. ORCHESTRATOR
# ============================================================

def run_orchestrator(*, sender, thread_id, inbox_id, message_id, raw_text, attachments, db):
    requirements = get_requirements_for_inbox(db, inbox_id)
    field_names = get_field_names(requirements)
    print(f"  📋 Requirements: {field_names}")

    state = db.query(ApplicantState).filter(ApplicantState.thread_id == thread_id).first()
    if not state:
        state = ApplicantState(
            thread_id=thread_id, candidate_email=sender,
            missing_fields=field_names, extracted_data={},
        )
        db.add(state)
        db.commit()

    if state.status == "APPROVED" and len(state.missing_fields or []) == 0:
        return {"status": "ignored", "reason": "already_approved"}

    # 1. Attachments
    print("  [1/4] 📎 attachment-handler")
    saved_files = attachment_handler(attachments, thread_id, sender, inbox_id, message_id, db)

    # 2. Parse email
    print("  [2/4] 🔍 email-parser")
    try:
        parser_response = email_parser_agent.run(f"""
    candidate_email: {sender}
    current_known_data: {json.dumps(state.extracted_data)}
    attached_file_types: {json.dumps(list(saved_files.keys()))}
    required_fields: {json.dumps(requirements)}

    email_body:
    {raw_text}
    """)
        parsed_data = _parse_agent_json(parser_response.content)
    except Exception as e:
        print(f"        ⚠️ {e}")
        parsed_data = {"extracted_data": {}, "summary": "Parse failed"}

    # 3. Merge
    current_extracted = dict(state.extracted_data or {})
    for file_type, file_path in saved_files.items():
        if file_type in field_names:
            current_extracted[file_type] = file_path
        for req in requirements:
            if req["field_type"] == "file" and req["name"] == file_type:
                current_extracted[req["name"]] = file_path
    llm_extracted = parsed_data.get("extracted_data", parsed_data)
    for key, value in llm_extracted.items():
        if key == "summary":
            continue
        if value and isinstance(value, str) and value.strip():
            current_extracted[key] = value
    state.extracted_data = current_extracted

    # 4. Triage
    print("  [3/4] ⚖️  application-triage")
    try:
        triage_response = triage_agent.run(f"""
    required_fields: {json.dumps(requirements)}
    extracted_data: {json.dumps(current_extracted)}
    """)
        _parse_agent_json(triage_response.content)
    except Exception as e:
        print(f"        ⚠️ {e}")

    # Server-side authority
    missing_fields = [fn for fn in field_names
                      if not (state.extracted_data.get(fn) or "").strip()
                      if isinstance(state.extracted_data.get(fn, ""), str)]
    # Handle non-string values (file paths are always strings, but be safe)
    missing_fields = []
    for fn in field_names:
        val = state.extracted_data.get(fn)
        if val is None:
            missing_fields.append(fn)
        elif isinstance(val, str) and not val.strip():
            missing_fields.append(fn)

    missing_field_objects = [r for r in requirements if r["name"] in missing_fields]

    old_status = state.status
    old_missing = list(state.missing_fields or [])
    state.missing_fields = missing_fields
    state.latest_message = raw_text
    state.reply_count = (state.reply_count or 0) + 1
    state.updated_at = datetime.now(timezone.utc)

    if not missing_fields:
        state.status = "APPROVED"
        state.missing_fields = []
        state.approved_at = datetime.now(timezone.utc)
    else:
        state.status = "PENDING"
        state.approved_at = None

    db.add(ApplicantStateHistory(
        thread_id=thread_id, old_status=old_status, new_status=state.status,
        old_missing_fields=old_missing, new_missing_fields=missing_fields,
    ))

    # 5. Compose reply
    print("  [4/4] ✉️  hr-reply-composer")
    try:
        composer_response = reply_composer_agent.run(f"""
    candidate_email: {sender}
    application_status: {state.status}
    missing_fields: {json.dumps(missing_field_objects)}
    items_received: {json.dumps(list(current_extracted.keys()))}
    """)
        composer_result = _parse_agent_json(composer_response.content)
        reply_text = composer_result.get("reply_draft", "")
    except Exception as e:
        print(f"        ⚠️ {e}")
        if state.status == "PENDING":
            missing_text = "\n".join([f"- {f['description']}" for f in missing_field_objects])
            reply_text = f"Thank you for your application.\n\nWe still need:\n\n{missing_text}\n\nPlease reply with the missing details.\n\nBest regards,\nHR Team"
        else:
            reply_text = "Thank you! We've received all required materials. Your application is now under review.\n\nBest regards,\nHR Team"

    db.commit()

    if reply_text:
        print(f"  📤 Sending reply to {sender}...")
        agentmail_client.inboxes.messages.reply(
            inbox_id=inbox_id, message_id=message_id, text=reply_text,
        )

    return {"status": "processed", "applicant_status": state.status}


# ============================================================
# 10. FASTAPI APP
# ============================================================
app = FastAPI(title="HR Triage Agent — Dynamic Skills Architecture")


# ── Dashboard ──

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    """Serve the admin dashboard."""
    html_path = os.path.join(os.path.dirname(__file__), "static", "dashboard.html")
    with open(html_path, "r", encoding="utf-8") as f:
        return f.read()


# ── Webhook ──

@app.post("/")
async def handle_agentmail_webhook(request: Request):
    payload = await request.json()
    if payload.get("event_type") != "message.received":
        return {"status": "ignored"}

    message_data = payload.get("message", {})
    sender = message_data.get("from_", "")
    thread_id = message_data.get("thread_id")
    inbox_id = message_data.get("inbox_id")
    message_id = message_data.get("message_id")
    raw_text = message_data.get("text", "")
    attachments = message_data.get("attachments", [])

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

    try:
        print(f"\n{'='*60}")
        print(f"  🎯 Thread: {thread_id}")
        print(f"  📧 From: {sender}")
        print(f"{'='*60}")

        result = run_orchestrator(
            sender=sender, thread_id=thread_id, inbox_id=inbox_id,
            message_id=message_id, raw_text=raw_text,
            attachments=attachments, db=db,
        )
        print(f"\n✅ Complete: {result}")
        return result
    except Exception as e:
        print(f"\n❌ Error: {e}")
        db.rollback()
        return {"status": "error", "detail": str(e)}
    finally:
        db.close()


# ── Applicants API ──

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


# ── Requirements API ──

@app.post("/requirements/{inbox_id}")
def create_requirements(inbox_id: str, payload: RequirementCreate):
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


# ── Files ──

@app.get("/files/{file_id}")
def get_file(file_id: int):
    db = SessionLocal()
    file_record = db.query(ApplicantFile).filter(ApplicantFile.id == file_id).first()
    db.close()
    if not file_record:
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path=file_record.file_path, filename=file_record.original_filename, media_type="application/octet-stream")


# ── Debug ──

@app.get("/skills")
def list_skills():
    return {
        name: {
            "description": s["description"],
            "execution_mode": s["execution_mode"],
            "license": s["license"],
            "metadata": s["metadata"],
            "source_file": s["source_file"],
        }
        for name, s in SKILLS.items()
    }


if __name__ == "__main__":
    print("🚀 Starting on port 8000...")
    print("📊 Dashboard: http://localhost:8000/dashboard\n")
    uvicorn.run(app, host="0.0.0.0", port=8000)