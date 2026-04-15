---
name: email-parser
description: >
  Extracts structured applicant data from raw email text based on a dynamic
  list of required fields. Use when processing incoming job application emails.
  For attachment handling use attachment-handler; for triage decisions use
  application-triage; for composing replies use hr-reply-composer.
license: MIT
metadata:
  skill-author: HR-Triage-System
  version: "2.0"
  category: hr-automation
  execution-mode: llm
  required-packages: []
---

# Email Parser Skill

Extracts structured applicant information from raw email content based on
dynamically configured required fields.

## Context

You will receive:
- `candidate_email`: The sender's email address
- `current_known_data`: JSON dict of previously extracted data across all emails in this thread
- `attached_file_types`: List of file types detected in the current email's attachments
- `required_fields`: JSON list of field objects that the employer requires, each with a `name` and `description`
- `email_body`: The raw email text

## Extraction Rules

### URL-Type Fields

For any field whose description mentions "URL", "link", or "profile", extract
URLs matching the relevant domain:

```python
import re

def extract_url(email_body: str, domain_hint: str) -> str:
    pattern = rf'https?://(?:www\.)?{re.escape(domain_hint)}[\w\-./]*'
    matches = re.findall(pattern, email_body, re.IGNORECASE)
    return matches[0] if matches else ""
```

Common domain hints by field name:
- linkedin → linkedin.com
- github → github.com
- twitter or x → x.com or twitter.com
- portfolio → any URL the candidate labels as their portfolio
- website → any URL the candidate labels as their website

### File-Type Fields

For any field whose description mentions "file", "document", "attachment",
"resume", or "CV":

- If the attached_file_types list contains a matching type, set the value to "attached"
- If the email contains a hosted link (Google Drive, Dropbox, OneDrive), extract it

### Text-Type Fields

For any field whose description mentions "text", "description", "summary",
"years", "experience", or "name":

- Extract the relevant text directly from the email body
- Keep it concise — one line or one short paragraph

### Important Rules

- You will receive the required_fields list dynamically — do NOT assume what fields exist
- Only extract fields that appear in the required_fields list
- Do NOT hallucinate URLs or data that is not explicitly in the email text
- If a field was already present in current_known_data with a valid value, preserve it
- If you cannot find data for a field, set it to an empty string

## Output Format

Return ONLY this JSON structure. No markdown fences. No explanation text.

The keys in extracted_data MUST match the name values from required_fields.

```json
{
  "extracted_data": {
    "field_name_1": "extracted value or empty string",
    "field_name_2": "extracted value or empty string"
  },
  "summary": "One-line summary of what the candidate provided in this email"
}
```