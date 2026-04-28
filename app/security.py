"""
Security utilities: rate limiting, spam detection, webhook verification.
"""
import hmac
import hashlib
import logging
from collections import defaultdict
from datetime import datetime, timezone

from .config import (
    RATE_LIMIT_WINDOW,
    RATE_LIMIT_MAX_REQUESTS,
    SPAM_KEYWORDS,
    WEBHOOK_SECRET,
    SLACK_WEBHOOK_URL,
)

logger = logging.getLogger(__name__)

# ============================================================
# RATE LIMITING
# ============================================================
rate_limit_store = defaultdict(list)


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


# ============================================================
# SPAM DETECTION
# ============================================================


def detect_spam(text: str, sender: str, retain_memory_func=None) -> tuple[bool, str]:
    """Simple keyword-based spam detection."""
    text_lower = text.lower()
    for keyword in SPAM_KEYWORDS:
        if keyword in text_lower:
            if retain_memory_func:
                retain_memory_func(
                    content=f"Sender {sender} flagged as spam because of keyword '{keyword}' on {datetime.now(timezone.utc)}"
                )
            return True, f"Spam keyword detected: {keyword}"
    
    # Check for excessive capitalization
    if len(text) > 50 and (sum(1 for c in text if c.isupper()) / len(text)) > 0.7:
        if retain_memory_func:
            retain_memory_func(
                content=f"Sender {sender} flagged as spam because of excessive capitalization on {datetime.now(timezone.utc)}"
            )
        return True, "Excessive capitalization detected"
    
    # Check for excessive repetition
    if len(text) > 20:
        words = text.split()
        if len(set(words)) < len(words) * 0.3:
            if retain_memory_func:
                retain_memory_func(
                    content=f"Sender {sender} flagged as spam because of excessive repetition on {datetime.now(timezone.utc)}"
                )
            return True, "Excessive repetition detected"
    
    return False, ""


def check_candidate_history(sender: str, recall_memory_func=None) -> tuple[bool, str]:
    """Check if sender has history of spam complaints."""
    try:
        if recall_memory_func:
            result = recall_memory_func(
                query=f"sender {sender} spam complaints history",
            )
            if result and ("confirmed spam" in result.lower() or "blocked" in result.lower()):
                return True, result[:200]
    except Exception as e:
        logger.warning(f"Hindsight spam check failed for {sender}: {e}")
    return False, ""


# ============================================================
# WEBHOOK SIGNATURE VERIFICATION
# ============================================================


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
# ESCALATION
# ============================================================


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
