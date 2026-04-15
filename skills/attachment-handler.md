---
name: attachment-handler
description: >
  Classifies and saves email attachments from job applicants. This is a
  deterministic skill — it MUST be executed as Python code, never interpreted
  by an LLM. Use when an incoming email contains attachments. For parsing
  email text use email-parser.
license: MIT
metadata:
  skill-author: HR-Triage-System
  version: "2.0"
  category: hr-automation
  execution-mode: deterministic
  required-packages: []
---

# Attachment Handler Skill

Saves and classifies email attachments into appropriate directories.
This skill is deterministic and must be executed as pure Python code.

## Classification Rules

Attachments are classified by filename keywords:

| Keyword in Filename | File Type      | Save Directory           |
|---------------------|----------------|--------------------------|
| "resume" or "cv"  | resume         | uploads/resumes/         |
| "cover"            | cover_letter   | uploads/cover_letters/   |
| (anything else)     | other          | uploads/other/           |

```python
def classify_attachment(filename: str) -> tuple[str, str]:
    """Returns (file_type, save_directory)."""
    lower = filename.lower()

    if any(kw in lower for kw in ["resume", "cv"]):
        return "resume", "uploads/resumes"
    elif "cover" in lower:
        return "cover_letter", "uploads/cover_letters"
    else:
        return "other", "uploads/other"
```

### Storage Convention

Stored filename format: {thread_id}_{attachment_id}_{original_filename}

This ensures uniqueness across threads and prevents filename collisions.

### Download Process

Call the AgentMail API to get the attachment's download URL
Download the file bytes from that URL
Write to the classified directory
Record the file metadata in the applicant_files database table

## Output Format

Returns a Python dict mapping file_type to saved file_path:

```json
{
  "resume": "uploads/resumes/thread123_att456_resume.pdf",
  "cover_letter": "uploads/cover_letters/thread123_att789_coverletter.pdf"
}
```

### Error Handling

If an attachment has no filename or no attachment_id, skip it silently.
If the download fails, log the error and continue processing remaining attachments.
Never let a single attachment failure crash the entire pipeline.