"""
orchestrator.py

Coordinates the three agents (email_parser → triage → reply_composer)
and all side-effects (DB writes, file handling, escalation, sending replies).
"""

import logging
from datetime import datetime, timezone

from mail_agent.agents import email_parser as parser_agent
from mail_agent.agents import triage as triage_agent
from mail_agent.agents import reply_composer as composer_agent

from mail_agent.models import ApplicantState, ApplicantStateHistory
from mail_agent.utils import (
    get_requirements,
    get_conversation_history,
    handle_attachments,
    trigger_escalation,
    agentmail_client,
)

logger = logging.getLogger(__name__)

MAX_REPLIES_PER_THREAD = 5
STALLED_THRESHOLD_DAYS = 7


# ── helpers ───────────────────────────────────────────────────────────────────

def _build_doc_context(extracted_texts: dict) -> str:
    if not extracted_texts:
        return ""
    lines = "\n".join(
        f"--- {k.upper()} ---\n{v}" for k, v in extracted_texts.items()
    )
    return f"\n\n=== EXTRACTED DOCUMENTS ===\n{lines}"


def _build_history_context(history: list[dict]) -> str:
    if not history:
        return ""
    lines = "\n".join(
        f"[{m['received_at']}] {m['sender']}: {m['text'][:200]}" for m in history
    )
    return f"\n\n=== CONVERSATION HISTORY ===\n{lines}"


def _merge_extracted(
    state: ApplicantState,
    requirements: list[dict],
    saved_files: dict,
    parser_result: dict,
) -> dict:
    """
    Merge file paths and parser output into the existing extracted_data dict.
    Returns the updated dict (does NOT mutate state yet).
    """
    extracted = dict(state.extracted_data or {})

    # Persist file paths for file-type requirements
    for file_type, path in saved_files.items():
        for req in requirements:
            if req["field_type"] == "file" and req["name"] == file_type:
                extracted[req["name"]] = path

    # Merge text fields from parser
    raw = parser_result.get("extracted_data", parser_result)
    for key, value in raw.items():
        if key == "summary" or value is None:
            continue
        if isinstance(value, dict) and "value" in value:
            value = value["value"]
        if isinstance(value, str) and value.strip():
            extracted[key] = value.strip()
            logger.info(f"  extracted {key}: {value.strip()[:80]}")

    return extracted


def _compute_missing(extracted: dict, field_names: list[str]) -> list[str]:
    return [
        fn for fn in field_names
        if not extracted.get(fn) or (
            isinstance(extracted.get(fn), str) and not extracted[fn].strip()
        )
    ]


# ── main entry ────────────────────────────────────────────────────────────────

def run(
    *,
    sender: str,
    thread_id: str,
    inbox_id: str,
    message_id: str,
    raw_text: str,
    attachments: list,
    db,
) -> dict:
    """
    Full pipeline for one inbound message.

    Returns a status dict e.g. {"status": "processed", "applicant_status": "PENDING"}.
    """
    logger.info(f"Processing thread={thread_id} from={sender}")

    requirements = get_requirements(db, inbox_id)
    field_names = [r["name"] for r in requirements]

    # ── 1. Load or create applicant state ────────────────────────────────────
    state = db.query(ApplicantState).filter(
        ApplicantState.thread_id == thread_id
    ).first()

    if not state:
        state = ApplicantState(
            thread_id=thread_id,
            candidate_email=sender,
            missing_fields=field_names,
            extracted_data={},
        )
        db.add(state)
        db.commit()

    if state.status == "APPROVED":
        return {"status": "ignored", "reason": "already_approved"}

    if (state.reply_count or 0) >= MAX_REPLIES_PER_THREAD:
        return {"status": "ignored", "reason": "reply_cap_reached"}

    # ── 2. Stalled detection ─────────────────────────────────────────────────
    if state.status == "PENDING" and state.updated_at and not state.stalled_at:
        updated_at = state.updated_at
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
        if (datetime.now(timezone.utc) - updated_at).days >= STALLED_THRESHOLD_DAYS:
            state.status = "STALLED"
            state.stalled_at = datetime.now(timezone.utc)
            trigger_escalation(thread_id, sender, "Application stalled for 7+ days")
            db.commit()

    # ── 3. Handle attachments ─────────────────────────────────────────────────
    saved_files, extracted_texts = handle_attachments(
        attachments, thread_id, sender, inbox_id, message_id, db
    )

    # ── 4. Email parser agent ─────────────────────────────────────────────────
    history = get_conversation_history(db, thread_id)
    doc_context = _build_doc_context(extracted_texts)
    history_context = _build_history_context(history)

    parser_result = parser_agent.run(
        sender=sender,
        current_known_data=dict(state.extracted_data or {}),
        saved_file_keys=list(saved_files.keys()),
        requirements=requirements,
        raw_text=raw_text,
        doc_context=doc_context,
        history_context=history_context,
    )

    # ── 5. Merge extracted data ───────────────────────────────────────────────
    extracted = _merge_extracted(state, requirements, saved_files, parser_result)
    state.extracted_data = extracted

    # ── 6. Triage agent ───────────────────────────────────────────────────────
    triage_result = triage_agent.run(
        requirements=requirements,
        extracted_data=extracted,
    )
    logger.info(f"  triage advisory missing: {triage_result.get('missing_fields', [])}")

    # Authoritative missing-fields check (deterministic, not LLM-dependent)
    missing_fields = _compute_missing(extracted, field_names)
    missing_field_objects = [r for r in requirements if r["name"] in missing_fields]

    # ── 7. Update state ───────────────────────────────────────────────────────
    old_status = state.status
    state.missing_fields = missing_fields
    state.latest_message = raw_text
    state.reply_count = (state.reply_count or 0) + 1
    state.updated_at = datetime.now(timezone.utc)
    state.status = "APPROVED" if not missing_fields else "PENDING"

    if state.status == "APPROVED":
        state.approved_at = datetime.now(timezone.utc)

    db.add(ApplicantStateHistory(
        thread_id=thread_id,
        old_status=old_status,
        new_status=state.status,
        old_missing_fields=list(state.missing_fields or []),
        new_missing_fields=missing_fields,
    ))

    # ── 8. Reply composer agent ───────────────────────────────────────────────
    reply_text = composer_agent.run(
        sender=sender,
        status=state.status,
        missing_field_objects=missing_field_objects,
        received_keys=list(extracted.keys()),
    )

    db.commit()

    # ── 9. Send reply ─────────────────────────────────────────────────────────
    if reply_text:
        try:
            agentmail_client.inboxes.messages.reply(
                inbox_id=inbox_id,
                message_id=message_id,
                text=reply_text,
            )
            logger.info(f"Reply sent to {sender}")
        except Exception as exc:
            logger.error(f"Failed to send reply for thread={thread_id}: {exc}")

    return {"status": "processed", "applicant_status": state.status}