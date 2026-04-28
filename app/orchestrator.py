"""
Main email processing orchestrator.
"""
import json
import logging
from datetime import datetime, timezone

from .database import (
    ApplicantState, ApplicantMessageLog, ApplicantStateHistory, SessionLocal
)
from .config import MAX_REPLIES_PER_THREAD, STALLED_THRESHOLD_DAYS
from .requirements import get_requirements_for_inbox, get_field_names
from .attachments import attachment_handler
from .email_queue import queue_email_for_sending
from .security import trigger_escalation
from .utils import retry_with_backoff, parse_agent_json
from hindsight_agno import HindsightTools, configure

logger = logging.getLogger(__name__)

# ============================================================
# HINDSIGHT MEMORY TOOLS
# ============================================================
_hindsight_tools_cache: dict[str, HindsightTools] = {}


def get_hindsight_tools(bank_id: str, **kwargs) -> HindsightTools:
    """Return a cached HindsightTools instance for a given bank_id."""
    if bank_id not in _hindsight_tools_cache:
        _hindsight_tools_cache[bank_id] = HindsightTools(bank_id=bank_id, **kwargs)
    return _hindsight_tools_cache[bank_id]


def get_candidate_memory_tools(candidate_email: str) -> HindsightTools:
    """Get memory tools for a specific candidate."""
    return get_hindsight_tools(
        f"candidate:{candidate_email}",
        enable_retain=True,
        enable_recall=True,
        enable_reflect=True,
    )


def get_spam_tools() -> HindsightTools:
    """Get spam registry tools."""
    return get_hindsight_tools("spam-registry")


# ============================================================
# CONVERSATION HISTORY
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
# RESUME SCORING
# ============================================================


def score_resume_against_requirements(resume_text: str, requirements: list[dict], extracted_data: dict, resume_scorer_agent) -> dict:
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
        result = parse_agent_json(response.content)
        return result
    except Exception as e:
        logger.error(f"Resume scoring failed: {e}")
        return {"overall_score": 0.0, "breakdown": {}, "reasoning": f"Scoring failed: {e}"}


# ============================================================
# MAIN ORCHESTRATOR
# ============================================================


def run_orchestrator(*, sender, thread_id, inbox_id, message_id, raw_text, attachments, db, agents, tracer):
    """Main orchestrator for processing incoming emails."""
    
    with tracer.start_as_current_span("run_orchestrator") as span:
        span.set_attribute("thread_id", thread_id)
        span.set_attribute("candidate_email", sender)
        
        email_parser_agent = agents["email_parser"]
        triage_agent = agents["triage"]
        reply_composer_agent = agents["reply_composer"]
        resume_scorer_agent = agents["resume_scorer"]
        
        def get_candidate_memory_context(candidate_email: str) -> str:
            try:
                tools = get_candidate_memory_tools(candidate_email)
                memory_summary = tools.reflect_on_memory(
                    run_context=None,
                    query="Summarize candidate profile, skills, submitted documents, previous conversations, and missing information."
                )
                if memory_summary:
                    return f"KNOWN CANDIDATE FACTS FROM PREVIOUS INTERACTIONS:\n{memory_summary}"
                return ""
            except Exception as e:
                logger.warning(f"Failed to fetch candidate memory for {candidate_email}: {e}")
                return ""

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

        # Reply cap check
        if (state.reply_count or 0) >= MAX_REPLIES_PER_THREAD:
            logger.warning(f"Reply cap reached for thread {thread_id}")
            return {
                "status": "ignored",
                "reason": "reply_cap_reached",
                "thread_id": thread_id,
            }

        # Stalled detection and escalation
        if state.status == "PENDING" and state.updated_at:
            updated_at = state.updated_at
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
        candidate_memory = get_candidate_memory_context(sender)
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

{candidate_memory} 

email_body:
{raw_text}
{document_context}
{history_context}
"""
            with tracer.start_as_current_span("email_parser"):
                parser_response = retry_with_backoff(lambda: email_parser_agent.run(email_prompt))
            parsed_data = parse_agent_json(parser_response.content)
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
            with tracer.start_as_current_span("triage"):
                triage_response = retry_with_backoff(lambda: triage_agent.run(triage_prompt))
            triage_result = parse_agent_json(triage_response.content)
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
            
            # Score resume against requirements when approved
            resume_text = extracted_texts.get("resume", "")
            if resume_text:
                print("  [Tier 4] 📊 Scoring resume against requirements...")
                score_result = score_resume_against_requirements(
                    resume_text,
                    requirements,
                    current_extracted,
                    resume_scorer_agent
                )
                state.extracted_data["_resume_score"] = score_result

                # Retain this in Hindsight for future reflection
                try:
                    tools = get_candidate_memory_tools(sender)
                    tools.retain_memory(
                        run_context=None,
                        content=(
                            f"Resume scored {score_result.get('overall_score')}/100. "
                            f"Strengths: {score_result.get('strengths')}. "
                            f"Weaknesses: {score_result.get('weaknesses')}."
                        )
                    )
                except Exception as e:
                    logger.warning(f"Failed to store hindsight resume memory: {e}")

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
            if state.status == "APPROVED":
                reply_text = f"""
Thank you for providing all the required details.

We have successfully received your application and supporting information. Our team will review everything and get back to you if there are any next steps.

Best regards,
HR Team
""".strip()
            else:
                try:
                    tools = get_candidate_memory_tools(sender)
                    candidate_context_raw = tools.reflect_on_memory(
                        run_context=None,
                        query="Summarize candidate communication style, tone, previous replies, and conversation behavior."
                    )
                    candidate_context = f"CANDIDATE COMMUNICATION HISTORY:\n{candidate_context_raw}" if candidate_context_raw else ""
                except Exception as e:
                    logger.warning(f"Failed to fetch candidate communication memory: {e}")
                    candidate_context = ""

                composer_prompt = f"""
candidate_email: {sender}
application_status: {state.status}
missing_fields: {json.dumps(missing_field_objects)}
items_received: {json.dumps(list(current_extracted.keys()))}
{candidate_context}
"""
                with tracer.start_as_current_span("reply_composer"):
                    composer_response = retry_with_backoff(lambda: reply_composer_agent.run(composer_prompt))
                
                composer_result = parse_agent_json(composer_response.content)
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
            queue_email_for_sending(inbox_id, message_id, reply_text, thread_id)

            try:
                tools = get_candidate_memory_tools(sender)
                tools.retain_memory(
                    run_context=None,
                    content=(
                        f"Sent reply on {datetime.now(timezone.utc)}. "
                        f"Application status: {state.status}. "
                        f"Missing fields requested: {missing_fields}. "
                        f"Reply summary: {reply_text[:300]}"
                    )
                )
            except Exception as e:
                logger.warning(f"Failed to store reply memory: {e}")

        return {"status": "processed", "applicant_status": state.status}


def process_webhook_background(sender: str, thread_id: str, inbox_id: str, message_id: str, raw_text: str, attachments: list, agents, tracer):
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
            attachments=attachments, db=db, agents=agents, tracer=tracer,
        )
        print(f"\n✅ Complete: {result}")
    except Exception as e:
        print(f"\n❌ Background Error: {e}")
        db.rollback()
    finally:
        db.close()
