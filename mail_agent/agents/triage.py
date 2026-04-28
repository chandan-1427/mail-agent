"""
agents/triage.py

Evaluates which required fields are still missing after the email-parser
has extracted what it can.

Input prompt shape
------------------
required_fields  : list  (JSON)
extracted_data   : dict  (JSON)

Output (raw JSON)
-----------------
{
  "missing_fields": ["<field_name>", ...],
  "complete": true | false
}
"""

import json
import logging

from ._base import build_agent
from mail_agent.utils import parse_json

logger = logging.getLogger(__name__)

_agent = build_agent("application-triage")


def run(*, requirements: list[dict], extracted_data: dict) -> dict:
    """
    Run the triage agent and return its result dict.

    Returns {"missing_fields": [], "complete": False} on failure so the
    orchestrator can fall back to its own field-presence check.
    """
    prompt = f"""
required_fields: {json.dumps(requirements)}
extracted_data: {json.dumps(extracted_data)}
""".strip()

    try:
        response = _agent.run(prompt)
        return parse_json(response.content)
    except Exception as exc:
        logger.error(f"[triage] agent failed: {exc}")
        return {"missing_fields": [], "complete": False}