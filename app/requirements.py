"""
Job requirements management.
"""
from .database import JobRequirement
from .config import MAX_REPLIES_PER_THREAD, STALLED_THRESHOLD_DAYS

# ============================================================
# FIELD VALIDATION
# ============================================================
VALID_FIELD_TYPES = {"url", "file", "text", "email", "phone"}

DEFAULT_REQUIREMENTS = [
    {"name": "full_name", "description": "Your full name", "field_type": "text"},
    {"name": "email", "description": "Your email address", "field_type": "email"},
    {"name": "linkedin", "description": "Your LinkedIn profile URL", "field_type": "url"},
    {"name": "github", "description": "Your GitHub profile URL", "field_type": "url"},
    {"name": "resume", "description": "Your resume as a file attachment or link", "field_type": "file"},
    {"name": "years_experience", "description": "Your total years of relevant experience", "field_type": "text"},
    {"name": "current_role", "description": "Your current job title or role", "field_type": "text"},
    {"name": "skills_summary", "description": "Brief summary of your key skills and technologies", "field_type": "text"},
]


def validate_field(field: dict) -> list[str]:
    """Validate a single field definition."""
    errors = []
    name = field.get("name", "")
    if not name or not isinstance(name, str):
        errors.append("Field 'name' is required and must be a non-empty string")
    elif " " in name or name != name.lower():
        errors.append(f"Field name '{name}' must be lowercase with no spaces (use underscores)")
    if not field.get("description"):
        errors.append(f"Field '{name}' must have a description")
    ft = field.get("field_type", "")
    if ft not in VALID_FIELD_TYPES:
        errors.append(f"Field '{name}' has invalid type '{ft}'. Must be one of: {VALID_FIELD_TYPES}")
    return errors


def validate_requirements(fields: list[dict]) -> list[str]:
    """Validate a list of field definitions."""
    if not fields:
        return ["At least one required field must be specified"]
    all_errors = []
    seen_names = set()
    for field in fields:
        all_errors.extend(validate_field(field))
        name = field.get("name", "")
        if name in seen_names:
            all_errors.append(f"Duplicate field name: '{name}'")
        seen_names.add(name)
    return all_errors


def get_requirements_for_inbox(db, inbox_id: str) -> list[dict]:
    """Get requirements for a specific inbox, falling back to defaults."""
    job_req = db.query(JobRequirement).filter(JobRequirement.inbox_id == inbox_id).first()
    if job_req and job_req.required_fields:
        return job_req.required_fields
    return DEFAULT_REQUIREMENTS


def get_field_names(requirements: list[dict]) -> list[str]:
    """Extract field names from requirements."""
    return [f["name"] for f in requirements]
