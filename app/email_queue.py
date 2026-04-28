"""
Async email queue management with dead-letter queue support.
"""
import logging
import threading
import time
from collections import deque
from datetime import datetime, timezone

from .config import MAX_QUEUE_SIZE
from .attachments import agentmail_client

logger = logging.getLogger(__name__)

# ============================================================
# EMAIL QUEUE
# ============================================================
email_queue = deque()
dead_letter_queue = deque()
queue_lock = threading.Lock()


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
    from .utils import retry_with_backoff
    
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


def start_email_queue_processor():
    """Start the email queue processor thread."""
    queue_thread = threading.Thread(target=process_email_queue, daemon=True)
    queue_thread.start()
    logger.info("Email queue processor started")
    return queue_thread
