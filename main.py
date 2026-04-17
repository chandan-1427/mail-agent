import os
import uvicorn
import json
import time
import logging
import hmac
import hashlib
from datetime import datetime, timezone
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

# Database imports
from sqlalchemy import Integer, create_engine, Column, String, JSON, DateTime, text
from sqlalchemy.orm import declarative_base, sessionmaker

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agentmail import AgentMail

from bindu.penguin.bindufy import bindufy

# Skills loader
from skills_loader import load_skills, get_skill_content

load_dotenv()

# ============================================================
# STRUCTURED LOGGING
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# ============================================================
# TIER 3: RATE LIMITING & SPAM DETECTION
# ============================================================
from collections import defaultdict
from datetime import timedelta

# Simple in-memory rate limiter
rate_limit_store = defaultdict(list)
RATE_LIMIT_WINDOW = timedelta(minutes=5)
RATE_LIMIT_MAX_REQUESTS = 10

# Reply caps to prevent excessive auto-replies
MAX_REPLIES_PER_THREAD = 5

# Tier 4: Stalled detection and escalation
STALLED_THRESHOLD_DAYS = 7
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")

def trigger_escalation(thread_id: str, sender: str, reason: str):
    """Trigger human-in-the-loop escalation (e.g., Slack notification)."""
    logger.warning(f"Escalation triggered for thread {thread_id}: {reason}")
    
    if SLACK_WEBHOOK_URL:
        try:
            import requests
            payload = {
                "text": f" *Application Escalation*\n\nThread: {thread_id}\nCandidate: {sender}\nReason: {reason}\n\nRequires human review.",
            }
            requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=10)
            logger.info(f"Slack notification sent for thread {thread_id}")
        except Exception as e:
            logger.error(f"Failed to send Slack notification: {e}")
    else:
        logger.info("SLACK_WEBHOOK_URL not configured, skipping notification")

def check_rate_limit(identifier: str) -> bool:
    """Check if identifier has exceeded rate limit."""
    now = datetime.now(timezone.utc)
    # Clean old entries
    rate_limit_store[identifier] = [
        ts for ts in rate_limit_store[identifier]
        if now - ts < RATE_LIMIT_WINDOW
    ]
    # Check limit
    if len(rate_limit_store[identifier]) >= RATE_LIMIT_MAX_REQUESTS:
        logger.warning(f"Rate limit exceeded for {identifier}")
        return False
    # Add current request
    rate_limit_store[identifier].append(now)
    return True

# Spam detection keywords
SPAM_KEYWORDS = [
    "viagra", "casino", "lottery", "winner", "congratulations",
    "bitcoin", "crypto", "investment opportunity", "nigerian prince",
    "click here", "free money", "urgent", "act now"
]

def detect_spam(text: str, sender: str) -> tuple[bool, str]:
    """Simple keyword-based spam detection."""
    text_lower = text.lower()
    for keyword in SPAM_KEYWORDS:
        if keyword in text_lower:
            return True, f"Spam keyword detected: {keyword}"
    
    # Check for excessive capitalization
    if len(text) > 50 and (sum(1 for c in text if c.isupper()) / len(text)) > 0.7:
        return True, "Excessive capitalization detected"
    
    # Check for excessive repetition
    if len(text) > 20:
        words = text.split()
        if len(set(words)) < len(words) * 0.3:
            return True, "Excessive repetition detected"
    
    return False, ""

# Webhook signature verification
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")

def verify_webhook_signature(payload: str, signature: str) -> bool:
    """Verify webhook signature using HMAC-SHA256."""
    if not WEBHOOK_SECRET:
        logger.warning("WEBHOOK_SECRET not set, skipping signature verification")
        return True  # Allow if secret not configured (dev mode)
    
    expected_signature = hmac.new(
        WEBHOOK_SECRET.encode(),
        payload.encode(),
        hashlib.sha256
    ).hexdigest()
    
    # Compare signatures safely
    return hmac.compare_digest(expected_signature, signature)

# ============================================================
# RETRY UTILITY
# ============================================================
def retry_with_backoff(func, max_retries=3, delay=1):
    """Simple retry logic for external API calls with exponential backoff."""
    for attempt in range(max_retries):
        try:
            return func()
        except Exception as e:
            if attempt == max_retries - 1:
                raise e
            wait_time = delay * (2 ** attempt)
            print(f"  ⚠️ Retry {attempt + 1}/{max_retries} after {wait_time}s: {e}")
            time.sleep(wait_time)

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
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    approved_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    stalled_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class ApplicantMessageLog(Base):
    __tablename__ = "applicant_message_log"
    id = Column(Integer, primary_key=True, autoincrement=True)
    thread_id = Column(String, index=True)
    sender_email = Column(String)
    message_id = Column(String)
    raw_text = Column(String)
    received_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


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
    uploaded_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class JobRequirement(Base):
    __tablename__ = "job_requirements"
    id = Column(Integer, primary_key=True, autoincrement=True)
    inbox_id = Column(String, unique=True, index=True, nullable=False)
    required_fields = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class ApplicantStateHistory(Base):
    __tablename__ = "applicant_state_history"
    id = Column(Integer, primary_key=True, autoincrement=True)
    thread_id = Column(String, index=True, nullable=False)
    old_status = Column(String)
    new_status = Column(String)
    old_missing_fields = Column(JSON)
    new_missing_fields = Column(JSON)
    changed_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


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


# Tier 2: Structured Output with Confidence Scoring
class ExtractedField(BaseModel):
    value: str
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence score 0-1")
    source: str = Field(description="Where this came from: email_body, resume, cover_letter, etc.")


class EmailParserResult(BaseModel):
    extracted_data: dict[str, ExtractedField]
    summary: str
    confidence_scores: dict[str, float] = Field(default_factory=dict)


class TriageDecision(BaseModel):
    is_approved: bool
    missing_fields: list[str]
    reasoning: str
    confidence: float = Field(ge=0.0, le=1.0)


# ============================================================
# 4. REQUIREMENT MANAGER (deterministic skill)
# ============================================================

VALID_FIELD_TYPES = {"url", "file", "text", "email", "phone"}

DEFAULT_REQUIREMENTS = [
    {"name": "full_name", "description": "Your full name", "field_type": "text"},
    {"name": "email", "description": "Your email address", "field_type": "email"},
    {"name": "linkedin", "description": "Your LinkedIn profile URL", "field_type": "url"},
    {"name": "github", "description": "Your GitHub profile URL", "field_type": "url"},
    {"name": "resume", "description": "Your resume as a file attachment or link", "field_type": "file"},
    {"name": "years_experience", "description": "Your total years of relevant experience", "field_type": "text"},
    {"name": "current_role", "description": "Your current job title or role", "field_type": "text"},
    {"name": "skills_summary", "description": "Brief summary of your key skills and technologies", "field_type": "text"},
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

# Tier 4: Multi-model routing
def _make_model(task_type: str = "default"):
    """Factory function to return appropriate model based on task type."""
    models = {
        "spam_detection": OpenAIChat(
            id="openai/gpt-4o-mini",  # Cheaper model for spam detection
            api_key=OPENROUTER_API_KEY,
            base_url="https://openrouter.ai/api/v1",
        ),
        "parsing": OpenAIChat(
            id="openai/gpt-4o",  # Balanced model for parsing
            api_key=OPENROUTER_API_KEY,
            base_url="https://openrouter.ai/api/v1",
        ),
        "triage": OpenAIChat(
            id="openai/o3-mini",  # Smartest model for triage decisions
            api_key=OPENROUTER_API_KEY,
            base_url="https://openrouter.ai/api/v1",
        ),
        "default": OpenAIChat(
            id="openai/gpt-4o",
            api_key=OPENROUTER_API_KEY,
            base_url="https://openrouter.ai/api/v1",
        ),
    }
    return models.get(task_type, models["default"])


def build_skill_agent(skill_name: str, agent_name: str | None = None, task_type: str = "default") -> Agent:
    skill_content = get_skill_content(SKILLS, skill_name)
    return Agent(
        name=agent_name or skill_name,
        model=_make_model(task_type),
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


# Tier 4: Build agents with appropriate models
email_parser_agent = build_skill_agent("email-parser", "Email Parser", task_type="parsing")
triage_agent = build_skill_agent("application-triage", "Triage Decision Agent", task_type="triage")
reply_composer_agent = build_skill_agent("hr-reply-composer", "Reply Composer", task_type="default")

# Tier 4: Resume scoring agent (uses smartest model for evaluation)
resume_scorer_agent = build_skill_agent("application-triage", "Resume Scorer", task_type="triage")

print("🤖 Skill-powered agents built with multi-model routing\n")


# ============================================================
# 7. DETERMINISTIC ATTACHMENT HANDLER
# ============================================================

agentmail_client = AgentMail(api_key=AGENTMAIL_API_KEY)


def extract_text_from_file(file_path: str, filename: str) -> str:
    """Extract text from PDF and text files."""
    try:
        lower_filename = filename.lower()
        
        # PDF extraction
        if lower_filename.endswith('.pdf'):
            try:
                import PyPDF2
                with open(file_path, 'rb') as f:
                    reader = PyPDF2.PdfReader(f)
                    text = ""
                    for page in reader.pages:
                        text += page.extract_text() + "\n"
                    return text.strip()[:10000]  # Limit to 10k chars
            except ImportError:
                print(f"  ⚠️ PyPDF2 not installed, skipping PDF text extraction")
                return ""
            except Exception as e:
                print(f"  ⚠️ Failed to extract PDF text: {e}")
                return ""
        
        # Text file extraction
        elif lower_filename.endswith(('.txt', '.md', '.csv')):
            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    return f.read()[:10000]
            except Exception as e:
                print(f"  ⚠️ Failed to extract text: {e}")
                return ""
        
        return ""
    except Exception as e:
        print(f"  ⚠️ Text extraction error: {e}")
        return ""


def attachment_handler(attachments, thread_id, sender, inbox_id, message_id, db):
    saved_files = {}
    extracted_texts = {}
    
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
                
                # Extract text from the file
                extracted_text = extract_text_from_file(file_path, original_filename)
                if extracted_text:
                    extracted_texts[file_type] = extracted_text
                    print(f"  📄 Extracted {len(extracted_text)} chars from {original_filename}")
                
                db.add(ApplicantFile(
                    thread_id=thread_id, candidate_email=sender, message_id=message_id,
                    file_type=file_type, original_filename=original_filename,
                    stored_filename=stored_filename, file_path=file_path,
                ))
        except Exception as e:
            print(f"  ⚠️ Failed to save attachment {original_filename}: {e}")
    
    return saved_files, extracted_texts


# ============================================================
# 8. RESUME SCORING (Tier 4)
# ============================================================

def score_resume_against_requirements(resume_text: str, requirements: list[dict], extracted_data: dict) -> dict:
    """Score resume against job requirements using AI."""
    if not resume_text:
        return {"overall_score": 0.0, "breakdown": {}, "reasoning": "No resume text provided"}
    
    try:
        # Build requirement descriptions
        req_descriptions = "\n".join([
            f"- {r['name']}: {r['description']}" 
            for r in requirements
        ])
        
        # Build extracted data summary
        extracted_summary = "\n".join([
            f"- {k}: {v}" 
            for k, v in extracted_data.items() 
            if v and k not in ["resume", "cover_letter"]
        ])
        
        scoring_prompt = f"""
You are an expert resume evaluator. Score the following resume against the job requirements.

JOB REQUIREMENTS:
{req_descriptions}

CANDIDATE EXTRACTED DATA:
{extracted_summary}

RESUME TEXT:
{resume_text[:8000]}

Provide a JSON response with:
{{
    "overall_score": <0-100 score>,
    "breakdown": {{
        "skills_match": <0-100>,
        "experience_match": <0-100>,
        "education_match": <0-100>,
        "relevance": <0-100>
    }},
    "strengths": ["list of strengths"],
    "weaknesses": ["list of weaknesses"],
    "reasoning": "brief explanation of the score"
}}
"""
        response = retry_with_backoff(lambda: resume_scorer_agent.run(scoring_prompt))
        result = _parse_agent_json(response.content)
        return result
    except Exception as e:
        logger.error(f"Resume scoring failed: {e}")
        return {"overall_score": 0.0, "breakdown": {}, "reasoning": f"Scoring failed: {e}"}


# ============================================================
# 10. ASYNC EMAIL QUEUE (Tier 4)
# ============================================================

from collections import deque
import threading

# Simple in-memory email queue (can be extended to Redis/RabbitMQ)
email_queue = deque()
dead_letter_queue = deque()
queue_lock = threading.Lock()
MAX_QUEUE_SIZE = 1000

def queue_email_for_sending(inbox_id: str, message_id: str, text: str, thread_id: str) -> bool:
    """Queue email for async sending with dead-letter handling."""
    with queue_lock:
        if len(email_queue) >= MAX_QUEUE_SIZE:
            logger.error(f"Email queue full, moving to dead letter queue: {thread_id}")
            dead_letter_queue.append({
                "inbox_id": inbox_id,
                "message_id": message_id,
                "text": text,
                "thread_id": thread_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "error": "Queue full"
            })
            return False
        
        email_queue.append({
            "inbox_id": inbox_id,
            "message_id": message_id,
            "text": text,
            "thread_id": thread_id,
            "attempts": 0,
            "queued_at": datetime.now(timezone.utc).isoformat(),
        })
        logger.info(f"Email queued for thread {thread_id}")
        return True

def process_email_queue():
    """Background thread to process email queue."""
    while True:
        with queue_lock:
            if not email_queue:
                time.sleep(1)
                continue
            
            email_task = email_queue.popleft()
        
        try:
            retry_with_backoff(lambda: agentmail_client.inboxes.messages.reply(
                inbox_id=email_task["inbox_id"],
                message_id=email_task["message_id"],
                text=email_task["text"],
            ))
            logger.info(f"Email sent successfully for thread {email_task['thread_id']}")
        except Exception as e:
            logger.error(f"Failed to send email for thread {email_task['thread_id']}: {e}")
            email_task["attempts"] += 1
            
            if email_task["attempts"] >= 3:
                logger.error(f"Max retries exceeded, moving to dead letter queue: {email_task['thread_id']}")
                with queue_lock:
                    dead_letter_queue.append({
                        **email_task,
                        "error": str(e),
                        "failed_at": datetime.now(timezone.utc).isoformat(),
                    })
            else:
                # Re-queue for retry
                with queue_lock:
                    email_queue.appendleft(email_task)
        
        time.sleep(0.5)

# Start email queue processor thread
queue_thread = threading.Thread(target=process_email_queue, daemon=True)
queue_thread.start()
logger.info("Email queue processor started")


# ============================================================
# 11. CONVERSATION HISTORY
# ============================================================

def get_conversation_history(db, thread_id: str, limit: int = 10) -> list[dict]:
    """Fetch full conversation history for a thread."""
    logs = db.query(ApplicantMessageLog).filter(
        ApplicantMessageLog.thread_id == thread_id
    ).order_by(ApplicantMessageLog.received_at.asc()).limit(limit).all()
    
    return [
        {
            "sender": log.sender_email,
            "message_id": log.message_id,
            "text": log.raw_text,
            "received_at": log.received_at.isoformat() if log.received_at else None,
        }
        for log in logs
    ]


# ============================================================
# 9. JSON PARSER
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
# 9. BACKGROUND TASKS
# ============================================================

def process_webhook_background(sender: str, thread_id: str, inbox_id: str, message_id: str, raw_text: str, attachments: list):
    """Background task to process webhook without blocking the response."""
    db = SessionLocal()
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
    except Exception as e:
        print(f"\n❌ Background Error: {e}")
        db.rollback()
    finally:
        db.close()


# ============================================================
# 10. ORCHESTRATOR
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

    if state.status == "APPROVED":
      print("  ✅ Already approved — skipping further processing")
      return {
          "status": "ignored",
          "reason": "already_approved",
          "thread_id": thread_id,
      }

    # Tier 3: Reply cap check
    if (state.reply_count or 0) >= MAX_REPLIES_PER_THREAD:
        logger.warning(f"Reply cap reached for thread {thread_id}")
        return {
            "status": "ignored",
            "reason": "reply_cap_reached",
            "thread_id": thread_id,
        }

    # Tier 4: Stalled detection and escalation
    if state.status == "PENDING" and state.updated_at:
        updated_at = state.updated_at

        # Normalize timezone-naive DB datetime values
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)

        now_utc = datetime.now(timezone.utc)
        days_since_update = (now_utc - updated_at).days

        if days_since_update >= STALLED_THRESHOLD_DAYS and not state.stalled_at:
            state.status = "STALLED"
            state.stalled_at = now_utc
            trigger_escalation(
                thread_id,
                sender,
                f"Application stalled for {days_since_update} days"
            )
            db.commit()

    # 1. Attachments
    print("  [1/4] 📎 attachment-handler")
    saved_files, extracted_texts = attachment_handler(attachments, thread_id, sender, inbox_id, message_id, db)

    # 2. Parse email with conversation history
    print("  [2/4] 🔍 email-parser")
    conversation_history = get_conversation_history(db, thread_id)
    print(f"  💬 Conversation history: {len(conversation_history)} messages")
    
    try:
        # Combine extracted document texts with email body
        document_context = ""
        if extracted_texts:
            document_context = "\n\n=== EXTRACTED DOCUMENT TEXT ===\n"
            for file_type, text in extracted_texts.items():
                document_context += f"\n--- {file_type.upper()} ---\n{text}\n"
        
        # Build conversation context
        history_context = ""
        if conversation_history:
            history_context = "\n\n=== CONVERSATION HISTORY ===\n"
            for msg in conversation_history:
                history_context += f"\n[{msg['received_at']}] {msg['sender']}: {msg['text'][:200]}...\n"
        
        email_prompt = f"""
    candidate_email: {sender}
    current_known_data: {json.dumps(state.extracted_data)}
    attached_file_types: {json.dumps(list(saved_files.keys()))}
    required_fields: {json.dumps(requirements)}

    email_body:
    {raw_text}
    {document_context}
    {history_context}
    """
        parser_response = retry_with_backoff(lambda: email_parser_agent.run(email_prompt))
        parsed_data = _parse_agent_json(parser_response.content)
    except Exception as e:
        print(f"        ⚠️ {e}")
        parsed_data = {"extracted_data": {}, "summary": "Parse failed"}

    # 3. Merge with confidence scoring
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

        if value is None:
            continue

        if isinstance(value, str):
            cleaned_value = value.strip()
            if cleaned_value:
                current_extracted[key] = cleaned_value
                print(f"  ✓ {key}: {cleaned_value[:80]}")

        elif isinstance(value, dict) and "value" in value:
            cleaned_value = str(value["value"]).strip()
            if cleaned_value:
                current_extracted[key] = cleaned_value
                print(f"  ✓ {key}: {cleaned_value[:80]}")

    state.extracted_data = current_extracted

    # 4. Triage
    print("  [3/4] ⚖️  application-triage")
    try:
        triage_prompt = f"""
    required_fields: {json.dumps(requirements)}
    extracted_data: {json.dumps(current_extracted)}
    """
        triage_response = retry_with_backoff(lambda: triage_agent.run(triage_prompt))
        triage_result = _parse_agent_json(triage_response.content)
        llm_missing = triage_result.get("missing_fields", [])
        print(f"        LLM triage result: missing={llm_missing}")
    except Exception as e:
        print(f"        {e}")
        llm_missing = []

    # Server-side authority - validate LLM result and handle edge cases
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
        
        # Tier 4: Score resume against requirements when approved
        resume_text = extracted_texts.get("resume", "")
        if resume_text:
            print("  [Tier 4] 📊 Scoring resume against requirements...")
            score_result = score_resume_against_requirements(resume_text, requirements, current_extracted)
            state.extracted_data["_resume_score"] = score_result
            print(f"  📊 Resume score: {score_result.get('overall_score', 0)}/100")
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
        # Tier 4: Send different replies based on approval status and missing fields
        if state.status == "APPROVED":
            reply_text = f"""
        Thank you for providing all the required details.

        We have successfully received your application and supporting information. Our team will review everything and get back to you if there are any next steps.

        Best regards,
        HR Team
        """.strip()
        else:
            composer_prompt = f"""
        candidate_email: {sender}
        application_status: {state.status}
        missing_fields: {json.dumps(missing_field_objects)}
        items_received: {json.dumps(list(current_extracted.keys()))}
        """
            composer_response = retry_with_backoff(lambda: reply_composer_agent.run(composer_prompt))
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
        print(f"  📤 Queueing reply to {sender}...")
        # Tier 4: Use email queue for async sending with retry logic
        queue_email_for_sending(inbox_id, message_id, reply_text, thread_id)

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


# ── Health Check (Tier 3) ──

@app.get("/health")
def health_check():
    """Health check endpoint for monitoring."""
    try:
        db = SessionLocal()
        # Test database connection
        db.execute(text("SELECT 1"))
        db.close()
        
        return JSONResponse({
            "status": "healthy",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "services": {
                "database": "connected",
                "agentmail": "configured" if AGENTMAIL_API_KEY else "missing",
                "openrouter": "configured" if OPENROUTER_API_KEY else "missing",
            },
            "skills_loaded": len(SKILLS),
        })
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return JSONResponse(
            status_code=503,
            content={
                "status": "unhealthy",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "error": str(e),
            }
        )


# ── Webhook ──

@app.post("/")
async def handle_agentmail_webhook(request: Request, background_tasks: BackgroundTasks):
    # Get raw body for signature verification
    body_bytes = await request.body()
    payload_str = body_bytes.decode('utf-8')
    
    # Tier 3: Webhook signature verification
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

    # Tier 3: Rate limiting check
    if not check_rate_limit(sender):
        logger.warning(f"Rate limit blocked: {sender}")
        return JSONResponse(
            status_code=429,
            content={"status": "rate_limited", "message": "Too many requests"}
        )

    # Tier 3: Spam detection
    is_spam, spam_reason = detect_spam(raw_text, sender)
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

    # Queue background processing
    background_tasks.add_task(
        process_webhook_background,
        sender=sender, thread_id=thread_id, inbox_id=inbox_id,
        message_id=message_id, raw_text=raw_text, attachments=attachments,
    )

    return {"status": "queued", "thread_id": thread_id}


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


bindu_config = {
    "author": "chandandakka2@gmail.com",
    "name": "hr_triage_agent",
    "description": "An HR triage agent that evaluates applicants, extracts required details, manages attachments, and replies with missing requirements.",
    "deployment": {
        "url": os.getenv("BINDU_DEPLOYMENT_URL", "http://localhost:3773"),
        "expose": True,
    },
    "skills": [],
}

def bindu_handler(messages: list[dict[str, str]]):
    latest_message = messages[-1]["content"] if messages else ""

    result = triage_agent.run(f"""
    You are the HR triage agent.

    Process this incoming request:

    {latest_message}
    """)

    return [
        {
            "role": "assistant",
            "content": result.content,
        }
    ]
    
if __name__ == "__main__":
    import threading
    import uvicorn

    def start_fastapi():
        print("🚀 Starting on port 8000...")
        print("📊 Dashboard: http://localhost:8000/dashboard")
        uvicorn.run(app, host="0.0.0.0", port=8000)

    # Start FastAPI in background thread
    threading.Thread(target=start_fastapi, daemon=True).start()

    print("🌻 Bindu Agent: http://localhost:3773")

    # Run Bindu in main thread
    bindufy(bindu_config, bindu_handler)