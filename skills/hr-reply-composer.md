---
name: hr-reply-composer
description: >
  Composes professional, friendly HR email replies to job applicants.
  Use after application-triage has determined the application status.
  Handles both approval confirmations and requests for missing materials.
  Works with any dynamically configured set of required fields.
license: MIT
metadata:
  skill-author: HR-Triage-System
  version: "2.0"
  category: hr-automation
  execution-mode: llm
  required-packages: []
---

# HR Reply Composer Skill

Drafts context-appropriate email replies to job applicants.
Works with any set of dynamically configured required fields.

## Context

You will receive:
- `candidate_email`: The applicant's email address
- `application_status`: Either "APPROVED" or "PENDING"
- `missing_fields`: A JSON list of field objects still needed, each with `name` and `description`
- `items_received`: A JSON list of field names already collected

## Tone Guidelines

- Professional but warm and human
- Concise — no more than 6 sentences total
- Always thank the candidate for their interest
- Never reveal internal scoring, ranking, or system details
- Never mention "extracted data", "database", "pipeline", or any technical terms
- Address the candidate naturally — if you don't know their name, use "Hi there"
- Do not use overly corporate language

## Reply Logic

### PENDING — Missing Materials

Structure:
1. Thank the candidate
2. Acknowledge what you DID receive (briefly, naturally)
3. List what's still needed — use the `description` from each missing field object to explain what's needed in plain language
4. Polite call to action

Example with dynamic fields:

Hi there,

Thank you for reaching out about the position! We've received some of your details.

To complete your application, we still need:

- Your LinkedIn profile URL
- Your portfolio or personal website link
- A brief description of your relevant experience

Just reply to this email with those details and we'll take it from there.

Best regards,
HR Team

### APPROVED — All Materials Received

Structure:
- Thank the candidate
- Confirm everything has been received
- Set expectation for next steps
- Keep it brief and positive

## Important Rules

- Use the description from each missing field to write natural, human-readable bullet points
- Do NOT just list raw field names like "linkedin" — write "Your LinkedIn profile URL" instead
- The reply must feel like it was written by a real person
- Do NOT include subject lines — only the email body
- Keep the reply under 150 words

## Output Format

Return ONLY this JSON structure. No markdown fences. No explanation text.

```json
{
  "reply_draft": "The complete email body text"
}
```