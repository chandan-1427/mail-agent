---
name: requirement-manager
description: >
  Manages dynamic job requirement configurations per inbox. This is a
  deterministic skill — it defines the data schema and validation rules
  for creating, updating, and reading job requirements. Use when an
  employer needs to configure what information they collect from applicants.
license: MIT
metadata:
  skill-author: HR-Triage-System
  version: "1.0"
  category: hr-automation
  execution-mode: deterministic
  required-packages: []
---

# Requirement Manager Skill

Manages dynamic per-inbox job requirement configurations.

## Data Schema

Each job requirement record contains:

| Column          | Type   | Description                                    |
|-----------------|--------|------------------------------------------------|
| id              | int    | Auto-incrementing primary key                  |
| inbox_id        | string | Unique identifier for the inbox                |
| required_fields | JSON   | List of field objects                          |
| created_at      | datetime | When the requirement was created             |

## Field Object Schema

Each field in `required_fields` is a JSON object with:

```json
{
  "name": "linkedin",
  "description": "Your LinkedIn profile URL",
  "field_type": "url"
}

Supported field_type values:

- url — A web URL (LinkedIn, GitHub, portfolio, etc.)
- file — A file attachment (resume, cover letter, etc.)
- text — Free-form text (years of experience, summary, etc.)
- email — An email address
- phone — A phone number

### Validation Rules

```python
VALID_FIELD_TYPES = {"url", "file", "text", "email", "phone"}

def validate_field(field: dict) -> list[str]:
    errors = []
    name = field.get("name", "")
    if not name or not isinstance(name, str):
        errors.append("Field 'name' is required and must be a non-empty string")
    elif " " in name or name != name.lower():
        errors.append(f"Field name '{name}' must be lowercase with no spaces")

    if not field.get("description"):
        errors.append(f"Field '{name}' must have a description")

    ft = field.get("field_type", "")
    if ft not in VALID_FIELD_TYPES:
        errors.append(f"Field '{name}' has invalid type '{ft}'. Must be one of: {VALID_FIELD_TYPES}")

    return errors

def validate_requirements(fields: list[dict]) -> list[str]:
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
```

### Default Requirements

When no JobRequirement exists for an inbox, use these defaults:

```json
[
  {"name": "linkedin", "description": "Your LinkedIn profile URL", "field_type": "url"},
  {"name": "github", "description": "Your GitHub profile URL", "field_type": "url"},
  {"name": "resume", "description": "Your resume as a file attachment or link", "field_type": "file"}
]
```

## API Operations

### Create Requirements

Input: inbox_id + list of field objects
Validate all fields before saving
Reject if inbox_id already has requirements (use update instead)

### Update Requirements

Input: inbox_id + new list of field objects
Validate all fields before saving
Replace the entire field list (not merge)

### Get Requirements

Input: inbox_id
Return the field list, or the defaults if none configured

### Delete Requirements

Input: inbox_id
Remove the record, reverting to defaults

## Output Format

Returns validation errors or the requirements data:

```json
{
  "errors": ["Field 'name' is required and must be a non-empty string"],
  "requirements": [
    {"name": "linkedin", "description": "Your LinkedIn profile URL", "field_type": "url"}
  ]
}
```