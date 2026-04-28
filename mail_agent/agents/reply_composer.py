"""
agents/reply_composer.py

Drafts a polite, context-aware reply to the candidate asking for the
fields that are still missing.

Input prompt shape
------------------
candidate_email      : str
application_status   : str  ("PENDING" | "APPROVED" | "STALLED")
missing_fields       : list[dict]  (JSON – full requirement objects)
items_received       : list[str]   (JSON – field names already collected)

Output (raw JSON)
-----------------
{
  "reply_draft": "<email body text>"
}
"""

import json
import logging

from ._base import build_agent
from mail_agent.utils import parse_json

logger = logging.getLogger(__name__)

_agent = build_agent("hr-reply-composer")

# Fallback template used when the agent errors out.
_FALLBACK_TEMPLATE = (
    "Thank you for your application.\n\n"
    "We still need:\n{missing_list}"
    "\n\nPlease reply with the missing details.\n\nBest regards,\nHR Team"
)

APPROVED_REPLY = (
    "Thank you for providing all required details. "
    "Our team will review your application and be in touch.\n\nBest regards,\nHR Team"
)


def run(
    *,
    sender: str,
    status: str,
    missing_field_objects: list[dict],
    received_keys: list[str],
) -> str:
    """
    Return the reply body as a plain string.

    If the application is APPROVED the standard sign-off is returned
    immediately without calling the agent.
    """
    if status == "APPROVED":
        return APPROVED_REPLY

    prompt = f"""
candidate_email: {sender}
application_status: {status}
missing_fields: {json.dumps(missing_field_objects)}
items_received: {json.dumps(received_keys)}
""".strip()

    try:
        response = _agent.run(prompt)
        result = parse_json(response.content)
        return result.get("reply_draft", "")
    except Exception as exc:
        logger.error(f"[reply-composer] agent failed: {exc}")
        missing_text = "\n".join(f"- {f['description']}" for f in missing_field_objects)
        return _FALLBACK_TEMPLATE.format(missing_list=missing_text)