"""
routes/webhook.py

POST /   — AgentMail inbound webhook
"""

import logging
import os

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import JSONResponse

from mail_agent.database import SessionLocal
from mail_agent.models import ApplicantMessageLog
from mail_agent.utils import check_rate_limit
import mail_agent.orchestrator

logger = logging.getLogger(__name__)

INBOX_ID = os.getenv("INBOX_ID")

router = APIRouter(tags=["webhook"])


def _process_in_background(
    sender: str,
    thread_id: str,
    inbox_id: str,
    message_id: str,
    raw_text: str,
    attachments: list,
) -> None:
    db = SessionLocal()
    try:
        result = mail_agent.orchestrator.run(
            sender=sender,
            thread_id=thread_id,
            inbox_id=inbox_id,
            message_id=message_id,
            raw_text=raw_text,
            attachments=attachments,
            db=db,
        )
        logger.info(f"Done: thread={thread_id} result={result}")
    except Exception as exc:
        logger.error(f"Background task failed for thread={thread_id}: {exc}")
        db.rollback()
    finally:
        db.close()


@router.post("/")
async def webhook(request: Request, background_tasks: BackgroundTasks):
    payload = await request.json()

    if payload.get("event_type") != "message.received":
        return {"status": "ignored"}

    msg = payload.get("message", {})
    sender = msg.get("from_", "")
    thread_id = msg.get("thread_id")
    inbox_id = msg.get("inbox_id")
    message_id = msg.get("message_id")
    raw_text = msg.get("text", "")
    attachments = msg.get("attachments", [])

    if not check_rate_limit(sender):
        return JSONResponse(status_code=429, content={"status": "rate_limited"})

    if INBOX_ID and INBOX_ID in sender:
        return {"status": "ignored", "reason": "self_sent"}

    db = SessionLocal()
    db.add(ApplicantMessageLog(
        thread_id=thread_id,
        sender_email=sender,
        message_id=message_id,
        raw_text=raw_text,
    ))
    db.commit()
    db.close()

    background_tasks.add_task(
        _process_in_background,
        sender, thread_id, inbox_id, message_id, raw_text, attachments,
    )
    return {"status": "queued", "thread_id": thread_id}