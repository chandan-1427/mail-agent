"""
Skills Loader — Reads skill markdown files with YAML frontmatter
and makes them available to agents as injectable context.
"""

import os
import glob
import yaml


SKILLS_DIR = os.path.join(os.path.dirname(__file__), "skills")


def load_skills(skills_dir: str = SKILLS_DIR) -> dict[str, dict]:
    """
    Loads all .md skill files from the skills directory.
    Returns a dict keyed by skill name.
    """
    skills = {}

    for filepath in sorted(glob.glob(os.path.join(skills_dir, "*.md"))):
        with open(filepath, "r", encoding="utf-8") as f:
            raw = f.read()

        if not raw.startswith("---"):
            print(f"  Skipping {filepath}: no YAML frontmatter found")
            continue

        parts = raw.split("---", 2)
        if len(parts) < 3:
            print(f"  Skipping {filepath}: malformed frontmatter")
            continue

        try:
            frontmatter = yaml.safe_load(parts[1])
        except yaml.YAMLError as e:
            print(f"  Skipping {filepath}: YAML parse error: {e}")
            continue

        body = parts[2].strip()
        name = frontmatter.get("name", os.path.basename(filepath))
        metadata = frontmatter.get("metadata", {})

        skills[name] = {
            "name": name,
            "description": frontmatter.get("description", ""),
            "metadata": metadata,
            "license": frontmatter.get("license", ""),
            "content": body,
            "execution_mode": metadata.get("execution-mode", "llm"),
            "source_file": filepath,
        }

        print(f"  Loaded skill: {name} (mode: {metadata.get('execution-mode', 'llm')})")

    return skills


def get_skill_content(skills: dict, skill_name: str) -> str:
    """Returns the full markdown body of a skill for prompt injection."""
    skill = skills.get(skill_name)
    if not skill:
        raise ValueError(f"Skill '{skill_name}' not found. Available: {list(skills.keys())}")
    return skill["content"]


def get_skill_routing_table(skills: dict) -> str:
    """
    Returns a formatted routing table of all available skills.
    Useful for giving an orchestrator agent awareness of what's available.
    """
    lines = ["Available Skills:", ""]
    for name, skill in skills.items():
        mode = skill["execution_mode"]
        lines.append(f"- **{name}** [{mode}]: {skill['description']}")
    return "\n".join(lines)


def get_llm_skills(skills: dict) -> dict[str, dict]:
    """Returns only skills that should be executed by an LLM agent."""
    return {k: v for k, v in skills.items() if v["execution_mode"] == "llm"}


def get_deterministic_skills(skills: dict) -> dict[str, dict]:
    """Returns only skills that should be executed as pure Python."""
    return {k: v for k, v in skills.items() if v["execution_mode"] == "deterministic"}