import json
import logging
import os
from collections import defaultdict
from datetime import datetime, timezone, timedelta

from agentmail import AgentMail

from mail_agent.database import SessionLocal
from mail_agent.models import ApplicantFile, ApplicantState, JobRequirement

logger = logging.getLogger(__name__)

# ============================================================
# CONSTANTS (used only by utils — will move to config.py later)
# ============================================================

AGENTMAIL_API_KEY = os.getenv("AGENTMAIL_API_KEY")
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")

RATE_LIMIT_WINDOW = timedelta(minutes=5)
RATE_LIMIT_MAX = 10

UPLOAD_DIR = "uploads"
RESUME_DIR = os.path.join(UPLOAD_DIR, "resumes")
COVER_LETTER_DIR = os.path.join(UPLOAD_DIR, "cover_letters")
OTHER_DIR = os.path.join(UPLOAD_DIR, "other")

VALID_FIELD_TYPES = {"url", "file", "text", "email", "phone"}

DEFAULT_REQUIREMENTS = [
    {"name": "full_name", "description": "Your full name", "field_type": "text"},
    {"name": "email", "description": "Your email address", "field_type": "email"},
    {"name": "linkedin", "description": "Your LinkedIn profile URL", "field_type": "url"},
    {"name": "github", "description": "Your GitHub profile URL", "field_type": "url"},
    {"name": "resume", "description": "Your resume as a file attachment or link", "field_type": "file"},
    {"name": "years_experience", "description": "Total years of relevant experience", "field_type": "text"},
    {"name": "current_role", "description": "Your current job title", "field_type": "text"},
    {"name": "skills_summary", "description": "Brief summary of your key skills", "field_type": "text"},
]

agentmail_client = AgentMail(api_key=AGENTMAIL_API_KEY)

# ============================================================
# RATE LIMITING
# ============================================================

rate_limit_store = defaultdict(list)


def check_rate_limit(identifier: str) -> bool:
    now = datetime.now(timezone.utc)
    rate_limit_store[identifier] = [
        ts for ts in rate_limit_store[identifier] if now - ts < RATE_LIMIT_WINDOW
    ]
    if len(rate_limit_store[identifier]) >= RATE_LIMIT_MAX:
        logger.warning(f"Rate limit exceeded for {identifier}")
        return False
    rate_limit_store[identifier].append(now)
    return True


# ============================================================
# REQUIREMENTS
# ============================================================

def validate_requirements(fields: list[dict]) -> list[str]:
    if not fields:
        return ["At least one field is required"]
    errors, seen = [], set()
    for f in fields:
        name = f.get("name", "")
        if not name or " " in name or name != name.lower():
            errors.append(f"Name '{name}' must be lowercase with no spaces")
        if not f.get("description"):
            errors.append(f"Field '{name}' needs a description")
        if f.get("field_type") not in VALID_FIELD_TYPES:
            errors.append(f"Field '{name}' has invalid type. Must be one of: {VALID_FIELD_TYPES}")
        if name in seen:
            errors.append(f"Duplicate field name: '{name}'")
        seen.add(name)
    return errors


def get_requirements(db, inbox_id: str) -> list[dict]:
    job_req = db.query(JobRequirement).filter(JobRequirement.inbox_id == inbox_id).first()
    return job_req.required_fields if job_req else DEFAULT_REQUIREMENTS


# ============================================================
# JSON PARSING
# ============================================================

def parse_json(raw) -> dict:
    # unwrap Agno response object
    if hasattr(raw, "content"):
        raw = raw.content
    if isinstance(raw, list):
        raw = " ".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in raw)
    if not isinstance(raw, str):
        raw = str(raw)

    # strip markdown fences
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
    if fenced:
        raw = fenced.group(1).strip()

    # clean parse
    try:
        return json.loads(raw.strip())
    except json.JSONDecodeError:
        pass

    # brace-match for first complete {...}
    brace_count, start = 0, None
    for i, ch in enumerate(raw):
        if ch == "{":
            if start is None:
                start = i
            brace_count += 1
        elif ch == "}":
            brace_count -= 1
            if brace_count == 0 and start is not None:
                try:
                    return json.loads(raw[start:i + 1])
                except json.JSONDecodeError:
                    start, brace_count = None, 0

    logging.getLogger(__name__).error(f"parse_json failed:\n{raw[:400]}")
    return {}


# ============================================================
# CONVERSATION HISTORY
# ============================================================

def get_conversation_history(db, thread_id: str) -> list[dict]:
    from mail_agent.models import ApplicantMessageLog
    logs = (
        db.query(ApplicantMessageLog)
        .filter(ApplicantMessageLog.thread_id == thread_id)
        .order_by(ApplicantMessageLog.received_at.asc())
        .limit(10)
        .all()
    )
    return [
        {
            "sender": l.sender_email,
            "text": l.raw_text,
            "received_at": l.received_at.isoformat() if l.received_at else None,
        }
        for l in logs
    ]


# ============================================================
# FILE HANDLING
# ============================================================

def extract_text_from_file(file_path: str, filename: str) -> str:
    try:
        if filename.lower().endswith(".pdf"):
            import PyPDF2
            with open(file_path, "rb") as f:
                reader = PyPDF2.PdfReader(f)
                return "".join(p.extract_text() + "\n" for p in reader.pages).strip()[:10000]
        elif filename.lower().endswith((".txt", ".md")):
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()[:10000]
    except Exception as e:
        logger.warning(f"Text extraction failed for {filename}: {e}")
    return ""


def handle_attachments(attachments, thread_id, sender, inbox_id, message_id, db) -> tuple[dict, dict]:
    saved_files, extracted_texts = {}, {}
    for att in attachments:
        filename = att.get("filename")
        att_id = att.get("attachment_id")
        if not filename or not att_id:
            continue
        lower = filename.lower()
        if any(k in lower for k in ["resume", "cv"]):
            file_type, save_dir = "resume", RESUME_DIR
        elif "cover" in lower:
            file_type, save_dir = "cover_letter", COVER_LETTER_DIR
        else:
            file_type, save_dir = "other", OTHER_DIR
        stored = f"{thread_id}_{att_id}_{filename}"
        path = os.path.join(save_dir, stored)
        try:
            resp = agentmail_client.inboxes.messages.get_attachment(
                inbox_id=inbox_id, message_id=message_id, attachment_id=att_id
            )
            url = getattr(resp, "download_url", None) or (
                resp.get("download_url") if isinstance(resp, dict) else None
            )
            if url:
                import urllib.request
                with urllib.request.urlopen(url) as r:
                    with open(path, "wb") as f:
                        f.write(r.read())
                saved_files[file_type] = path
                text = extract_text_from_file(path, filename)
                if text:
                    extracted_texts[file_type] = text
                db.add(ApplicantFile(
                    thread_id=thread_id, candidate_email=sender, message_id=message_id,
                    file_type=file_type, original_filename=filename,
                    stored_filename=stored, file_path=path,
                ))
        except Exception as e:
            logger.warning(f"Failed to save attachment {filename}: {e}")
    return saved_files, extracted_texts


# ============================================================
# ESCALATION
# ============================================================

def trigger_escalation(thread_id: str, sender: str, reason: str):
    logger.warning(f"Escalation: thread={thread_id} reason={reason}")
    if not SLACK_WEBHOOK_URL:
        return
    try:
        import requests
        requests.post(SLACK_WEBHOOK_URL, json={
            "text": f"*HR Escalation*\nThread: {thread_id}\nCandidate: {sender}\nReason: {reason}"
        }, timeout=10)
    except Exception as e:
        logger.error(f"Slack notification failed: {e}")