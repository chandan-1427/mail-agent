---
name: application-triage
description: >
  Evaluates whether a job application is complete by comparing extracted data
  against a dynamic list of required fields. Use after email-parser and
  attachment-handler have both run and their results have been merged.
  For composing the response email use hr-reply-composer.
license: MIT
metadata:
  skill-author: HR-Triage-System
  version: "2.0"
  category: hr-automation
  execution-mode: llm
  required-packages: []
---

# Application Triage Skill

Determines whether a candidate's application is complete or still missing
required information. Works with any set of dynamically configured required fields.

## Context

You will receive:
- `required_fields`: A JSON list of field objects, each with `name` and `description`
- `extracted_data`: A JSON dict of all data collected so far for this candidate

## Decision Logic

A field is considered **present** if and only if:
1. It exists as a key in `extracted_data`
2. Its value is not null
3. Its value is not an empty string
4. Its value is not a string containing only whitespace

```python
def evaluate_application(extracted_data: dict, required_fields: list[dict]) -> dict:
    missing = []
    for field in required_fields:
        field_name = field["name"]
        value = extracted_data.get(field_name)
        if value is None:
            missing.append(field_name)
        elif isinstance(value, str) and not value.strip():
            missing.append(field_name)

    return {
        "is_approved": len(missing) == 0,
        "missing_fields": missing,
        "reasoning": "All fields present" if not missing else f"Missing: {', '.join(missing)}"
    }
```

### Important Rules

- Do NOT assume any specific set of fields — use exactly what is in required_fields
- Be strict: a field with value "" is NOT present
- Be generous with format: "attached" IS a valid value (means attachment-handler saved it)
- File paths like "uploads/resumes/thread_123_resume.pdf" ARE valid values
- Do not invent or assume data that is not in extracted_data

## Output Format

Return ONLY this JSON structure. No markdown fences. No explanation text.

```json
{
  "is_approved": true,
  "missing_fields": [],
  "reasoning": "All required fields are present"
}
```