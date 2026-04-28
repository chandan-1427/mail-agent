"""
agents/_base.py
Shared model instance and factory for building skill-backed agents.
"""

import os
from dotenv import load_dotenv
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from skills_loader import load_skills, get_skill_content

load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

# ── shared model ──────────────────────────────────────────────────────────────
model = OpenAIChat(
    id="openai/gpt-4o-mini",
    api_key=OPENROUTER_API_KEY,
    base_url="https://openrouter.ai/api/v1",
)

# ── skills registry (loaded once) ─────────────────────────────────────────────
SKILLS = load_skills()


def build_agent(skill_name: str) -> Agent:
    """Return an Agent wired to the named skill."""
    skill = SKILLS[skill_name]
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