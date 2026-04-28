"""
AI agent building and management.
"""
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from .config import OPENROUTER_API_KEY

# ============================================================
# MODEL FACTORY
# ============================================================


def _make_model(task_type: str = "default"):
    """Factory function to return appropriate model based on task type."""
    models = {
        "spam_detection": OpenAIChat(
            id="openai/gpt-4o-mini",
            api_key=OPENROUTER_API_KEY,
            base_url="https://openrouter.ai/api/v1",
        ),
        "parsing": OpenAIChat(
            id="openai/gpt-4o-mini",
            api_key=OPENROUTER_API_KEY,
            base_url="https://openrouter.ai/api/v1",
        ),
        "triage": OpenAIChat(
            id="openai/gpt-4o-mini",
            api_key=OPENROUTER_API_KEY,
            base_url="https://openrouter.ai/api/v1",
        ),
        "default": OpenAIChat(
            id="openai/gpt-4o-mini",
            api_key=OPENROUTER_API_KEY,
            base_url="https://openrouter.ai/api/v1",
        ),
    }
    return models.get(task_type, models["default"])


def build_skill_agent(skill_name: str, skills: dict, agent_name: str | None = None, task_type: str = "default") -> Agent:
    """Build an agent configured with a specific skill."""
    from skills_loader import get_skill_content
    
    skill_content = get_skill_content(skills, skill_name)
    return Agent(
        name=agent_name or skill_name,
        model=_make_model(task_type),
        description=skills[skill_name]["description"],
        instructions=[
            f"You are executing the '{skill_name}' skill. Follow these instructions exactly:",
            "",
            skill_content,
            "",
            "CRITICAL: Return ONLY raw JSON as specified in the Output Format section.",
            "Do NOT wrap your response in markdown code fences.",
            "Do NOT include any text before or after the JSON.",
        ],
        markdown=False,
    )


# ============================================================
# AGENT INSTANCES
# ============================================================


def initialize_agents(skills: dict):
    """Initialize all skill-powered agents."""
    email_parser_agent = build_skill_agent("email-parser", skills, "Email Parser", task_type="parsing")
    triage_agent = build_skill_agent("application-triage", skills, "Triage Decision Agent", task_type="triage")
    reply_composer_agent = build_skill_agent("hr-reply-composer", skills, "Reply Composer", task_type="default")
    resume_scorer_agent = build_skill_agent("application-triage", skills, "Resume Scorer", task_type="triage")
    
    return {
        "email_parser": email_parser_agent,
        "triage": triage_agent,
        "reply_composer": reply_composer_agent,
        "resume_scorer": resume_scorer_agent,
    }
