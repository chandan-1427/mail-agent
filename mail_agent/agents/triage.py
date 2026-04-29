# triage.py
from functools import lru_cache
import json
import logging

from ._base import build_agent_with_static, _log_cache_metrics
from mail_agent.model_factory import extract_json

logger = logging.getLogger(__name__)


@lru_cache(maxsize=16)
def _get_agent(requirements_json: str):
    requirements = json.loads(requirements_json)
    field_names = ", ".join(r["name"] for r in requirements)
    return build_agent_with_static(
        skill_name="application-triage",
        extra_static=[
            f"Required field names: {field_names}",
        ],
    )


def _requirements_key(requirements: list[dict]) -> str:
    return json.dumps(
        sorted(requirements, key=lambda x: x["name"]),
        sort_keys=True, separators=(",", ":"),
    )


def run(*, requirements: list[dict], extracted_data: dict) -> dict:
    agent = _get_agent(_requirements_key(requirements))

    # ✅ Only extracted_data is dynamic — everything else is in system prompt
    prompt = f"extracted_data: {json.dumps(extracted_data)}"

    try:
        response = agent.run(prompt)
        _log_cache_metrics("triage", response)
        return extract_json(response.content)
    except Exception as exc:
        logger.error(f"[triage] agent failed: {exc}")
        return {"missing_fields": [], "complete": False}