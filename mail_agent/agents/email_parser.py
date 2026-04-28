"""
agents/email_parser.py

Parses inbound candidate emails and extracts structured data from the body
and any attached documents.

Input prompt shape
------------------
candidate_email      : str
current_known_data   : dict  (JSON)
attached_file_types  : list  (JSON)
required_fields      : list  (JSON)
email_body           : str
<optional doc / history context>

Output (raw JSON)
-----------------
{
  "extracted_data": {
    "<field_name>": "<value>",
    ...
  }
}
"""

import json
import logging

from ._base import build_agent
from mail_agent.utils import parse_json

logger = logging.getLogger(__name__)

# Agent is built once at import time.
_agent = build_agent("email-parser")


def run(
    *,
    sender: str,
    current_known_data: dict,
    saved_file_keys: list[str],
    requirements: list[dict],
    raw_text: str,
    doc_context: str = "",
    history_context: str = "",
) -> dict:
    """
    Run the email-parser agent and return the extracted_data dict.

    Returns an empty dict on failure so the caller can continue gracefully.
    """
    prompt = f"""
candidate_email: {sender}
current_known_data: {json.dumps(current_known_data)}
attached_file_types: {json.dumps(saved_file_keys)}
required_fields: {json.dumps(requirements)}
email_body: {raw_text}
{doc_context}
{history_context}
""".strip()

    try:
        response = _agent.run(prompt)
        parsed = parse_json(response.content)
        return parsed
    except Exception as exc:
        logger.error(f"[email-parser] agent failed: {exc}")
        return {"extracted_data": {}}