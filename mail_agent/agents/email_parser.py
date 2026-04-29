"""
agents/email_parser.py
"""

import json
import logging
from functools import lru_cache

from ._base import build_agent_with_static, _log_cache_metrics
from mail_agent.model_factory import extract_json

logger = logging.getLogger(__name__)


@lru_cache(maxsize=16)
def _get_agent(requirements_json: str):
    """
    One agent instance per unique requirements set.
    requirements_json is stable and sorted — used as cache key.
    Baking requirements into system prompt = longer stable prefix = more cache hits.
    """
    requirements = json.loads(requirements_json)
    field_list = "\n".join(
        f"  - {r['name']}: {r.get('description', '')}"
        for r in requirements
    )
    return build_agent_with_static(
        skill_name="email-parser",
        extra_static=[
            f"Required fields to extract:\n{field_list}",
        ],
    )


def _requirements_key(requirements: list[dict]) -> str:
    """Stable sorted JSON string — identical requirements always produce identical key."""
    return json.dumps(
        sorted(requirements, key=lambda x: x["name"]),
        sort_keys=True,
        separators=(",", ":"),
    )


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
    # ✅ Agent selected by requirements — system prompt is stable per job role
    agent = _get_agent(_requirements_key(requirements))

    # ✅ User turn: only truly dynamic data — changes per candidate/email
    prompt = f"""
candidate_email: {sender}
current_known_data: {json.dumps(current_known_data)}
attached_file_types: {json.dumps(saved_file_keys)}
email_body: {raw_text}
{doc_context}
{history_context}
""".strip()

    try:
        response = agent.run(prompt)
        _log_cache_metrics("email-parser", response)
        return extract_json(response.content)
    except Exception as exc:
        logger.error(f"[email-parser] agent failed: {exc}")
        return {"extracted_data": {}}