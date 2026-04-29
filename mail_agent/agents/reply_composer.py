"""
agents/reply_composer.py
"""

import json
import logging
from functools import lru_cache

from ._base import build_agent, _log_cache_metrics
from mail_agent.model_factory import extract_json

logger = logging.getLogger(__name__)


# ✅ Single agent instance — system prompt never changes
# lru_cache(maxsize=1) ensures byte-identical system prompt on every call
@lru_cache(maxsize=1)
def _get_agent():
    return build_agent("hr-reply-composer", agent_type="reply")


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
    sender: str,          # ✅ intentionally excluded from prompt
    status: str,
    missing_field_objects: list[dict],
    received_keys: list[str],
) -> str:
    if status == "APPROVED":
        return APPROVED_REPLY  # ✅ zero LLM cost on approved

    # ✅ Normalize + sort inputs so identical data = identical string = cache hit
    sorted_missing = sorted(missing_field_objects, key=lambda x: x["name"])
    sorted_received = sorted(received_keys)

    # ✅ User turn: only truly dynamic data, NO sender (changes per candidate)
    prompt = (
        f"application_status: {status}\n"
        f"missing_fields: {json.dumps(sorted_missing, sort_keys=True, separators=(',', ':'))}\n"
        f"items_received: {json.dumps(sorted_received, separators=(',', ':'))}"
    )

    try:
        response = _get_agent().run(prompt)
        _log_cache_metrics("reply-composer", response)
        result = extract_json(response.content)
        return result.get("reply_draft", "")
    except Exception as exc:
        logger.error(f"[reply-composer] agent failed: {exc}")
        missing_text = "\n".join(f"- {f['description']}" for f in missing_field_objects)
        return _FALLBACK_TEMPLATE.format(missing_list=missing_text)