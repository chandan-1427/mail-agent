"""
agents/_base.py
Shared model factory and agent builder for skill-backed agents.
Supports per-agent model configuration with MiniMax prompt caching.
"""

import logging
from agno.agent import Agent
from skills_loader import load_skills, get_skill_content
from mail_agent.model_factory import build_model, get_model_config

# ── skills registry (loaded once) ─────────────────────────────────────────────
SKILLS = load_skills()
logger = logging.getLogger(__name__)

def build_agent(skill_name: str, agent_type: str = "parser") -> Agent:
    """
    Return an Agent wired to the named skill with configured model.

    Args:
        skill_name: Name of the skill to load (e.g., "email-parser")
        agent_type: Type of agent for model config ("parser", "triage", "reply")

    Returns:
        Configured Agno Agent instance
    """
    skill = SKILLS[skill_name]
    config = get_model_config(agent_type)

    model = build_model(
        model_id=config["model_id"],
        enable_caching=config["enable_caching"],
        fallback_models=config["fallback_models"],
    )

    return Agent(
        name=skill_name,
        model=model,
        description=skill["description"],
        instructions=[
            f"You are executing the '{skill_name}' skill. Follow these instructions exactly:",
            get_skill_content(SKILLS, skill_name),
            "CRITICAL: Return ONLY raw JSON. No markdown fences, no extra text.",
        ],
        markdown=False,
    )


def build_agent_with_static(
    skill_name: str,
    extra_static: list[str],
) -> Agent:
    """
    Like build_agent() but injects extra static content into system prompt.
    Use when you have per-job-role content (requirements) that never changes
    mid-conversation — baking it into system prompt maximises cache prefix length.
    """
    skill = SKILLS[skill_name]
    config = get_model_config(
        "parser" if "parser" in skill_name
        else "triage" if "triage" in skill_name
        else "reply"
    )
    model = build_model(
        model_id=config["model_id"],
        enable_caching=config["enable_caching"],
        fallback_models=config["fallback_models"],
    )
    return Agent(
        name=skill_name,
        model=model,
        description=skill["description"],
        instructions=[
            # ✅ All of this is static per job role — entire block cached
            f"You are executing the '{skill_name}' skill. Follow these instructions exactly:",
            get_skill_content(SKILLS, skill_name),
            *extra_static,              # ← requirements baked in here
            "CRITICAL: Return ONLY raw JSON. No markdown fences, no extra text.",
        ],
        markdown=False,
    )

    
# make sure this exists at module level in _base.py
def _log_cache_metrics(agent_name: str, response) -> None:
    try:
        metrics = getattr(response, "metrics", None)
        if metrics is None:
            logger.info(f"[{agent_name}] ⚠️  no metrics on response")
            return

        cache_read    = getattr(metrics, "cache_read_tokens",  0) or 0
        cache_written = getattr(metrics, "cache_write_tokens", 0) or 0
        input_tokens  = getattr(metrics, "input_tokens",       0) or 0
        cost          = getattr(metrics, "cost",               0) or 0

        if cache_read:
            logger.info(f"[{agent_name}] ✅ cache HIT   — read={cache_read} input={input_tokens} cost=${cost:.6f}")
        elif cache_written:
            logger.info(f"[{agent_name}] 📝 cache WRITE — written={cache_written} input={input_tokens} cost=${cost:.6f}")
        else:
            logger.info(f"[{agent_name}] ❌ cache MISS  — input={input_tokens} cost=${cost:.6f}")

    except Exception as e:
        logger.warning(f"[{agent_name}] _log_cache_metrics error: {e}")