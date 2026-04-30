# Mail Agent — AI-Powered HR Triage System

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.135+-green.svg)](https://fastapi.tiangolo.com/)
[![Docker](https://img.shields.io/badge/Docker-Ready-blue.svg)](https://www.docker.com/)

An intelligent HR automation system that processes job applications via email, using AI-powered skills to extract data, evaluate completeness, and generate professional responses. Built on a modular skills architecture with dynamic per-inbox requirements, prompt caching for cost optimization, Langfuse observability, and comprehensive audit trails.

## 🚀 Features

- **AI-Powered Triage Pipeline**: Three-agent pipeline (email-parser → triage → reply-composer) orchestrated automatically
- **Dynamic Skills Architecture**: Modular AI skills loaded from YAML-frontmatter markdown files
- **Prompt Caching**: MiniMax auto-caching + Anthropic explicit `cache_control` for cost reduction
- **Per-Agent Model Configuration**: Each agent (parser, triage, reply) can use a different model with fallback chains
- **Attachment Management**: Automatic classification, download, and text extraction (PDF/TXT) for resumes, cover letters, and other files
- **Webhook Integration**: Real-time email processing via AgentMail webhooks with background task processing
- **Admin Dashboard**: Dark-themed web UI for viewing applicants and managing requirements
- **RESTful API**: Full CRUD operations for applicants, job requirements, and file access
- **Langfuse Tracing**: OpenTelemetry-based observability for agent runs (optional, auto-disabled without keys)
- **Stalled Application Detection**: Automatic escalation to Slack when applications are pending 7+ days
- **Rate Limiting**: In-memory rate limiter (10 requests / 5 minutes per sender)
- **Reply Caps**: Maximum 5 auto-replies per thread to prevent loops
- **Full Audit Trail**: Every status change recorded in `ApplicantStateHistory`

## 🔄 Application Status Flow

```
NEW EMAIL ──▶ PENDING ──▶ (all fields present) ──▶ APPROVED
                    │
                    └──▶ (7+ days stalled) ──▶ STALLED ──▶ Slack Escalation
```

- **PENDING**: Missing one or more required fields; agent sends a follow-up email
- **APPROVED**: All required fields collected; confirmation email sent (no LLM call needed)
- **STALLED**: No update for 7+ days; Slack notification triggered for human review

## 🏗️ System Architecture

### High-Level Flow

```
┌─────────────────┐    ┌───────────┐    ┌─────────────────────────────────┐
│   AgentMail     │───▶│   ngrok   │───▶│   mail_agent.main (FastAPI)     │
│   Webhooks      │    │ (HTTPS)   │    │   POST / → Background Task     │
└─────────────────┘    └───────────┘    └──────────────┬──────────────────┘
                                         │              │
                                         ▼              ▼
                               ┌─────────────────┐  ┌──────────────┐
                               │  Orchestrator    │  │  Langfuse    │
                               │  (pipeline)      │  │  Tracing     │
                               │                  │  │  (optional)  │
                               │ 1. Attachments   │  └──────────────┘
                               │ 2. Email Parser  │
                               │ 3. Data Merge    │
                               │ 4. Triage        │
                               │ 5. Reply Composer│
                               └────────┬─────────┘
                                        │
                              ┌─────────┴──────────┐
                              ▼                    ▼
                       ┌───────────┐       ┌──────────────┐
                       │ Database  │       │ AgentMail    │
                       │ SQLite /  │       │ Reply API    │
                       │ PostgreSQL│       └──────────────┘
                       └───────────┘
```

### Processing Pipeline

1. **Webhook Reception** — AgentMail sends `message.received` events to `POST /`
2. **Security Checks** — Rate limiting, self-send detection
3. **Message Logging** — Raw message stored in `ApplicantMessageLog`
4. **Background Task** — Webhook returns immediately; processing is async via FastAPI `BackgroundTasks`
5. **Stalled Detection** — If `PENDING` for 7+ days, mark `STALLED` + Slack escalation
6. **Attachment Handler** — Classify (resume/cover_letter/other), download, extract text (PDF/TXT)
7. **Email Parser Agent** — Extract structured data from email + document text + conversation history
8. **Data Merge** — Combine parser output with attachment file paths into `extracted_data`
9. **Triage Agent** — Evaluate which required fields are still missing
10. **Deterministic Missing-Fields Check** — Authoritative check independent of LLM output
11. **State Update** — Update `ApplicantState`, write `ApplicantStateHistory` record
12. **Reply Composer Agent** — Generate professional follow-up (or static confirmation if `APPROVED`)
13. **Send Reply** — Via AgentMail `inboxes.messages.reply()`

## 📂 Project Structure

```
mail-agent/
├── mail_agent/                    # Main Python package
│   ├── main.py                    # FastAPI app entry point (121 lines)
│   ├── orchestrator.py            # Pipeline coordinator (221 lines)
│   ├── database.py                # SQLAlchemy engine + session (26 lines)
│   ├── models.py                  # SQLAlchemy ORM models (65 lines)
│   ├── schemas.py                 # Pydantic request schemas (11 lines)
│   ├── utils.py                   # Helpers: rate limiting, attachments, JSON parsing (231 lines)
│   ├── model_factory.py           # OpenRouter model builder + prompt caching (263 lines)
│   ├── agents/                    # AI agent modules
│   │   ├── _base.py              # Shared agent builder + cache metrics (105 lines)
│   │   ├── email_parser.py       # Email data extraction agent (73 lines)
│   │   ├── triage.py             # Application completeness agent (43 lines)
│   │   └── reply_composer.py     # HR reply generation agent (63 lines)
│   └── routes/                    # FastAPI route modules
│       ├── webhook.py            # POST / — AgentMail webhook (87 lines)
│       ├── applicants.py         # GET /applicants (65 lines)
│       ├── requirements.py       # CRUD /requirements/{inbox_id} (91 lines)
│       └── misc.py               # /health, /dashboard, /files, /skills (67 lines)
├── skills/                        # Skill definitions (YAML frontmatter + markdown)
│   ├── email-parser.md            # Extracts structured data from emails (92 lines)
│   ├── attachment-handler.md      # Deterministic file processing (73 lines)
│   ├── application-triage.md      # Evaluates application completeness (72 lines)
│   ├── hr-reply-composer.md       # Generates professional responses (91 lines)
│   └── requirement-manager.md     # Manages dynamic field requirements (141 lines)
├── skills_loader.py               # Loads skills from YAML-frontmatter .md files (86 lines)
├── static/
│   └── dashboard.html             # Dark-themed admin dashboard UI (1010 lines)
├── uploads/                       # File storage (auto-created at startup)
│   ├── resumes/
│   ├── cover_letters/
│   └── other/
├── pyproject.toml                 # Dependencies (uv-managed)
├── uv.lock                        # Lock file
├── Dockerfile                     # Multi-stage build with uv (39 lines)
├── docker-compose.yml             # PostgreSQL + agent services (50 lines)
├── .env.example                   # Environment variable template
└── README.md                      # This file
```

## 🧠 Skills Architecture

Skills are markdown files with YAML frontmatter that define agent behavior. They are loaded at startup by `skills_loader.py` and injected into Agno agent system prompts.

### Skill Types

| Type | Description | Example |
|------|-------------|---------|
| **LLM** (`execution-mode: llm`) | Executed by an AI agent; returns JSON | email-parser, application-triage, hr-reply-composer |
| **Deterministic** (`execution-mode: deterministic`) | Executed as pure Python code | attachment-handler, requirement-manager |

### Core Skills

| Skill | Type | Purpose | Key Features |
|-------|------|---------|--------------|
| **email-parser** | LLM | Extracts applicant data from email content | URL extraction by domain, file-type detection, dynamic field support, conversation history context |
| **attachment-handler** | Deterministic | Classifies and saves file attachments | Resume/CV keyword detection, cover letter detection, PDF text extraction, metadata DB tracking |
| **application-triage** | LLM | Evaluates application completeness | Strict empty-string rejection, "attached" accepted as valid, dynamic field support |
| **hr-reply-composer** | LLM | Generates professional email responses | Professional tone, uses field descriptions (not raw names), <150 words, static reply for APPROVED |
| **requirement-manager** | Deterministic | Manages per-inbox job requirements | Field validation (name/description/type), duplicate detection, default fallback config |

### Adding New Skills

1. Create a `.md` file in `skills/` directory
2. Add YAML frontmatter:
   ```yaml
   ---
   name: your-skill
   description: What this skill does
   license: MIT
   metadata:
     execution-mode: llm  # or deterministic
   ---
   ```
3. Write skill instructions in the markdown body with a defined JSON output format
4. The skill is automatically loaded on next server restart
5. Reference it from an agent module in `mail_agent/agents/`

## 🤖 Agent Architecture

### Agent Pipeline

Each agent is built using `agno.Agent` with a skill-injected system prompt and a per-agent configured OpenRouter model.

```
┌─────────────────────────────────────────────────────────┐
│                    Orchestrator                          │
│                                                         │
│  ┌──────────────┐   ┌──────────────┐   ┌─────────────┐ │
│  │ Email Parser  │──▶│   Triage     │──▶│Reply Composer│ │
│  │ (LLM skill)  │   │ (LLM skill)  │   │ (LLM skill)  │ │
│  └──────────────┘   └──────────────┘   └─────────────┘ │
│         │                   │                  │         │
│    extract_json        extract_json      extract_json   │
│         │                   │                  │         │
│    _merge_extract      _compute_missing   APPROVED?     │
│                              │             static reply │
│                              ▼                          │
│                     deterministic check                 │
└─────────────────────────────────────────────────────────┘
```

### Prompt Caching Strategy

The system maximizes prompt cache hits:

- **System prompts** are stable per job role (requirements baked in) → long cache prefix
- **User turns** contain only truly dynamic data (email body, extracted_data) → minimal cache miss
- **Agent instances** are `lru_cache`d by requirements hash → identical system prompt bytes on every call
- **MiniMax models** auto-cache at the provider level (no explicit markers needed)
- **Anthropic models** use `CachingOpenRouter` which injects `cache_control: ephemeral` on system messages

### Model Configuration

Each agent type has independent model configuration via environment variables:

| Agent | Default Model | Config Prefix | Caching |
|-------|--------------|---------------|---------|
| Email Parser | `minimax/minimax-m2.5` | `PARSER_` | Auto (MiniMax) |
| Triage | `minimax/minimax-m2.5` | `TRIAGE_` | Auto (MiniMax) |
| Reply Composer | `minimax/minimax-m2.5` | `REPLY_` | Auto (MiniMax) |

Each can be switched to Anthropic (e.g. `anthropic/claude-haiku-4-5-20251001`) with `*_ENABLE_CACHING=true` to enable explicit cache control markers. Fallback model chains (up to 2 fallbacks) are supported via `*_FALLBACK_MODELS`.

### Cache Metrics Logging

Every agent call logs cache hit/miss metrics:
- `✅ cache HIT` — tokens served from cache (low cost)
- `📝 cache WRITE` — new prefix cached for future hits
- `❌ cache MISS` — full input processed at standard cost

## 🗄️ Database Schema

Five SQLAlchemy models backed by SQLite (dev) or PostgreSQL (prod):

### ApplicantState (`applicant_triage`)
| Column | Type | Description |
|--------|------|-------------|
| `id` | Integer, PK | Auto-increment |
| `thread_id` | String, unique, indexed | AgentMail thread ID |
| `candidate_email` | String, indexed | Applicant's email |
| `status` | String | `PENDING`, `APPROVED`, or `STALLED` |
| `extracted_data` | JSON | All extracted applicant information |
| `missing_fields` | JSON | List of still-missing field names |
| `latest_message` | String | Most recent email body |
| `reply_count` | Integer | Number of auto-replies sent |
| `created_at` | DateTime (UTC) | First seen |
| `updated_at` | DateTime (UTC) | Last processed |
| `approved_at` | DateTime (UTC), nullable | When all fields collected |
| `stalled_at` | DateTime (UTC), nullable | When 7-day threshold hit |

### ApplicantMessageLog (`applicant_message_log`)
| Column | Type | Description |
|--------|------|-------------|
| `id` | Integer, PK | Auto-increment |
| `thread_id` | String, indexed | Thread identifier |
| `sender_email` | String | Sender address |
| `message_id` | String | AgentMail message ID |
| `raw_text` | String | Full email body |
| `received_at` | DateTime (UTC) | When received |

### ApplicantFile (`applicant_files`)
| Column | Type | Description |
|--------|------|-------------|
| `id` | Integer, PK | Auto-increment |
| `thread_id` | String, indexed | Thread identifier |
| `candidate_email` | String | Applicant's email |
| `message_id` | String | Source message |
| `file_type` | String | `resume`, `cover_letter`, or `other` |
| `original_filename` | String | Original upload name |
| `stored_filename` | String | Sanitized stored name |
| `file_path` | String | Full path on disk |
| `uploaded_at` | DateTime (UTC) | When saved |

### JobRequirement (`job_requirements`)
| Column | Type | Description |
|--------|------|-------------|
| `id` | Integer, PK | Auto-increment |
| `inbox_id` | String, unique, indexed | AgentMail inbox ID |
| `required_fields` | JSON | List of field definition objects |
| `created_at` | DateTime (UTC) | When created |
| `updated_at` | DateTime (UTC) | Last modified |

### ApplicantStateHistory (`applicant_state_history`)
| Column | Type | Description |
|--------|------|-------------|
| `id` | Integer, PK | Auto-increment |
| `thread_id` | String, indexed | Thread identifier |
| `old_status` | String | Previous status |
| `new_status` | String | New status |
| `old_missing_fields` | JSON | Previous missing list |
| `new_missing_fields` | JSON | New missing list |
| `changed_at` | DateTime (UTC) | When changed |

### Default Requirements (8 fields)

When no `JobRequirement` exists for an inbox, these defaults are used:

| # | Name | Field Type | Description |
|---|------|-----------|-------------|
| 1 | `full_name` | text | Your full name |
| 2 | `email` | email | Your email address |
| 3 | `linkedin` | url | Your LinkedIn profile URL |
| 4 | `github` | url | Your GitHub profile URL |
| 5 | `resume` | file | Your resume as a file attachment or link |
| 6 | `years_experience` | text | Total years of relevant experience |
| 7 | `current_role` | text | Your current job title |
| 8 | `skills_summary` | text | Brief summary of your key skills |

Custom requirements can be configured per inbox via the `/requirements/{inbox_id}` API.

## 📡 API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/` | AgentMail webhook handler |
| `GET` | `/health` | Health check (DB ping + skills count) |
| `GET` | `/dashboard` | Admin dashboard UI (HTML) |
| `GET` | `/applicants` | List all applicants (optional `?status=` filter) |
| `GET` | `/applicants/{thread_id}` | Get single applicant state |
| `POST` | `/requirements/{inbox_id}` | Create custom requirements |
| `PUT` | `/requirements/{inbox_id}` | Update custom requirements |
| `GET` | `/requirements/{inbox_id}` | Get requirements for inbox |
| `DELETE` | `/requirements/{inbox_id}` | Delete custom requirements |
| `GET` | `/files/{file_id}` | Download uploaded attachment |
| `GET` | `/skills` | List loaded skills with metadata |

## 📡 API Documentation

### Webhook Processing

#### `POST /` — AgentMail Webhook

Accepts `message.received` events. Returns immediately after rate-limit check and message logging; actual processing runs in a background task.

**Request Body:**
```json
{
  "event_type": "message.received",
  "message": {
    "from_": "applicant@example.com",
    "thread_id": "thread-123",
    "inbox_id": "inbox-456",
    "message_id": "msg-789",
    "text": "Email content...",
    "attachments": [
      { "filename": "resume.pdf", "attachment_id": "att-123" }
    ]
  }
}
```

**Response:** `{"status": "queued", "thread_id": "thread-123"}`

**Error responses:**
- `429` — Rate limited (10 req / 5 min per sender)
- `{"status": "ignored"}` — Not a `message.received` event or self-sent email

### Applicant Management

#### `GET /applicants` — List Applicants

Query parameters:
- `status` (optional): Filter by `PENDING`, `APPROVED`, or `STALLED`

**Response:**
```json
{
  "applicants": [
    {
      "thread_id": "thread-123",
      "candidate_email": "applicant@example.com",
      "status": "PENDING",
      "extracted_data": {"linkedin": "https://linkedin.com/in/..."},
      "missing_fields": ["github", "resume"],
      "reply_count": 2,
      "created_at": "2026-04-17T09:27:00Z",
      "updated_at": "2026-04-17T09:30:00Z",
      "approved_at": null
    }
  ],
  "total": 1
}
```

#### `GET /applicants/{thread_id}` — Get Applicant State

Returns detailed state for a specific applicant thread. Returns `404` if not found.

### Requirements Management

#### Field Schema
```json
{
  "name": "linkedin",
  "description": "Your LinkedIn profile URL",
  "field_type": "url"
}
```

**Supported field types:** `url`, `file`, `text`, `email`, `phone`

**Validation rules:**
- `name` must be lowercase with no spaces
- `description` is required
- `field_type` must be one of the supported types
- Duplicate names are rejected

#### `POST /requirements/{inbox_id}` — Create Requirements
**Request:**
```json
{
  "required_fields": [
    { "name": "linkedin", "description": "Your LinkedIn profile URL", "field_type": "url" },
    { "name": "resume", "description": "Your resume file", "field_type": "file" }
  ]
}
```
Returns `409` if requirements already exist for this inbox.

#### `PUT /requirements/{inbox_id}` — Update Requirements
Replaces the entire field list. Creates the record if it doesn't exist.

#### `GET /requirements/{inbox_id}` — Get Requirements
Returns custom requirements if configured, otherwise the 8 default fields. Includes `is_custom` boolean.

#### `DELETE /requirements/{inbox_id}` — Delete Requirements
Returns `404` if no custom requirements exist. Reverts to defaults after deletion.

### File Management

#### `GET /files/{file_id}` — Download Attachment
Returns the original file as `application/octet-stream`. Returns `404` if file ID not found.

### System Endpoints

#### `GET /skills` — List Available Skills
Returns metadata for all loaded skills (name, description, execution_mode).

#### `GET /health` — Health Check
Pings the database and returns status, timestamp, and skills count. Returns `503` if unhealthy.

#### `GET /dashboard` — Admin Dashboard
Serves the dark-themed HTML admin interface.

## ⚙️ Configuration

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENROUTER_API_KEY` | Yes | OpenRouter API key for AI models |
| `DATABASE_URL` | Yes | Database connection string (SQLite or PostgreSQL) |
| `AGENTMAIL_API_KEY` | Yes | AgentMail API key for email processing |
| `INBOX_ID` | Yes | AgentMail inbox ID for applications |
| `AGENTMAIL_WEBHOOK_SECRET` | No | Webhook validation secret |
| `SLACK_WEBHOOK_URL` | No | Slack webhook URL for stalled application escalation |
| `LANGFUSE_PUBLIC_KEY` | No | Langfuse public key for tracing |
| `LANGFUSE_SECRET_KEY` | No | Langfuse secret key for tracing |
| `PARSER_MODEL_ID` | No | Model for email parser (default: `minimax/minimax-m2.5`) |
| `PARSER_ENABLE_CACHING` | No | Enable Anthropic cache_control for parser (default: `false`) |
| `PARSER_FALLBACK_MODELS` | No | Comma-separated fallback models for parser |
| `TRIAGE_MODEL_ID` | No | Model for triage agent (default: `minimax/minimax-m2.5`) |
| `TRIAGE_ENABLE_CACHING` | No | Enable Anthropic cache_control for triage (default: `false`) |
| `TRIAGE_FALLBACK_MODELS` | No | Comma-separated fallback models for triage |
| `REPLY_MODEL_ID` | No | Model for reply composer (default: `minimax/minimax-m2.5`) |
| `REPLY_ENABLE_CACHING` | No | Enable Anthropic cache_control for reply (default: `false`) |
| `REPLY_FALLBACK_MODELS` | No | Comma-separated fallback models for reply |
| `HINDSIGHT_API_URL` | No | Hindsight API URL (local or cloud) |
| `HINDSIGHT_API_KEY` | No | Hindsight API key (required for cloud) |
| `BINDU_DEPLOYMENT_URL` | No | Bindu agent deployment URL |

### Database Configuration

**Local Development (SQLite):**
```bash
DATABASE_URL=sqlite:///./mail_agent.db
```

**Production (PostgreSQL):**
```bash
DATABASE_URL=postgresql://hrtriage:password@localhost:5432/hrtriage_db
```

**Docker Compose:**
```bash
DATABASE_URL=postgresql://hrtriage:hrtriage_password@db:5432/hrtriage_db
```

> Tables are auto-created at startup via `init_db()`. No manual migration step needed.

### Example `.env` File

```bash
# AI Configuration
OPENROUTER_API_KEY=sk-or-v1-your-openrouter-key

# Database
DATABASE_URL=sqlite:///./mail_agent.db

# AgentMail Integration
AGENTMAIL_API_KEY=am-your-agentmail-key
INBOX_ID=inbox-your-inbox-id
AGENTMAIL_WEBHOOK_SECRET=your-webhook-secret

# Model Configuration (per-agent)
PARSER_MODEL_ID=minimax/minimax-m2.5
TRIAGE_MODEL_ID=minimax/minimax-m2.5
REPLY_MODEL_ID=minimax/minimax-m2.5
PARSER_ENABLE_CACHING=false
TRIAGE_ENABLE_CACHING=false
REPLY_ENABLE_CACHING=false
PARSER_FALLBACK_MODELS=anthropic/claude-haiku-4.5,anthropic/claude-sonnet-4.6
TRIAGE_FALLBACK_MODELS=anthropic/claude-haiku-4.5,anthropic/claude-sonnet-4.6
REPLY_FALLBACK_MODELS=anthropic/claude-haiku-4.5,anthropic/claude-sonnet-4.6

# Langfuse Tracing (optional)
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=

# Slack Escalation (optional)
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...

# Bindu Agent (optional)
BINDU_DEPLOYMENT_URL=http://localhost:3773
```

## 🚀 Getting Started

### Local Setup (SQLite — fastest)

1. **Clone and install:**
   ```bash
   git clone <repository-url>
   cd mail-agent
   uv sync          # or: pip install -e .
   ```

2. **Create `.env` file** (see example above — minimum: `OPENROUTER_API_KEY`, `DATABASE_URL`, `AGENTMAIL_API_KEY`, `INBOX_ID`)

3. **Start the server:**
   ```bash
   uvicorn mail_agent.main:app --reload
   ```
   Database tables are auto-created at startup.

4. **Start ngrok** (separate terminal):
   ```bash
   ngrok http 8000
   ```

5. **Register the webhook** in AgentMail with your ngrok HTTPS URL pointing to `/`

6. **Verify:**
   - Dashboard: `http://localhost:8000/dashboard`
   - API docs: `http://localhost:8000/docs`
   - Health: `http://localhost:8000/health`

### Docker Compose (production-like)

```bash
# Start all services (PostgreSQL + agent)
docker-compose up -d

# View logs
docker-compose logs -f

# Stop services
docker-compose down
```

**Services:**
- **db**: PostgreSQL 16 with health checks
- **agent**: FastAPI app with Bindu agent

**Ports:**
- `8000`: FastAPI API and dashboard
- `3773`: Bindu agent interface
- `5432`: PostgreSQL

**Volumes:** `db_data` (database), `uploads_data` (file attachments)

## 🧪 Testing

### Manual webhook simulation with `curl`

```bash
curl -X POST http://localhost:8000/ \
  -H "Content-Type: application/json" \
  -d '{
    "event_type": "message.received",
    "message": {
      "from_": "applicant@example.com",
      "thread_id": "thread-123",
      "inbox_id": "your-inbox-id",
      "message_id": "msg-123",
      "text": "Hello, I am applying for the job. My LinkedIn is https://linkedin.com/in/example.",
      "attachments": []
    }
  }'
```

**Expected response:** `{"status": "queued", "thread_id": "thread-123"}`

After processing completes (check logs), verify the applicant state:
```bash
curl http://localhost:8000/applicants/thread-123
```

### E2E test with a real AgentMail email

1. Send an email to the configured AgentMail inbox
2. Watch the `uvicorn` logs for processing output
3. Open `http://localhost:8000/dashboard` to review state

### List loaded skills

```bash
curl http://localhost:8000/skills
```

## 📦 Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| **FastAPI** | 0.135+ | Web framework |
| **Uvicorn** | 0.44+ | ASGI server |
| **SQLAlchemy** | 2.0+ | ORM for database operations |
| **Agno** | 2.5+ | AI agent framework |
| **AgentMail** | 0.4+ | Email webhook integration |
| **OpenAI** | 2.31+ | AI model client (via OpenRouter) |
| **PyPDF2** | 3.0+ | PDF text extraction |
| **PyYAML** | 6.0+ | YAML frontmatter parsing for skills |
| **Requests** | 2.31+ | HTTP client for Slack webhooks |
| **python-dotenv** | 1.0+ | Environment variable loading |
| **psycopg2-binary** | 2.9+ | PostgreSQL adapter |
| **Langfuse** | 4.5+ | LLM observability (optional) |
| **OpenTelemetry SDK** | 1.41+ | Tracing infrastructure |
| **openinference-instrumentation-agno** | 0.1+ | Agno auto-instrumentation |
| **Bindu** | 2026.3+ | Agent deployment platform |
| **x402** | <0.4 | Payment protocol |
| **hindsight-agno** | 0.4+ | Hindsight Agno integration |
| **nest-asyncio** | 1.6+ | Async compatibility |

## 🔧 Development Notes

- Database tables are auto-created at startup via `init_db()` — no manual migration needed
- The app ignores webhook events that are not `message.received`
- The webhook root endpoint is `POST /`
- Approved applicants get a static reply (zero LLM cost) — no agent call is made
- The `utils.py` `parse_json` function uses brace-counting for robust JSON extraction from LLM output
- The `model_factory.py` `extract_json` is the preferred JSON parser (also used by agents)
- Agent instances are `lru_cache`d — restart the server to pick up skill changes

### Debugging

**Enable debug logging:**
```bash
uvicorn mail_agent.main:app --reload --log-level debug
```

**Common issues:**
- **Database connection**: Verify `DATABASE_URL` format
- **API keys**: Check `.env` file is in the project root
- **Webhook failures**: Ensure AgentMail can reach your endpoint (ngrok running?)
- **Skill errors**: Check YAML frontmatter syntax in `skills/*.md`
- **Tracing warnings**: Set `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` or ignore the warnings

### Database Operations

**Reset (SQLite):**
```bash
rm mail_agent.db
```

**Reset (Docker):**
```bash
docker-compose down -v
```

**Query directly:**
```bash
sqlite3 mail_agent.db "SELECT * FROM applicant_triage;"
```

## 🤝 Contributing

1. Fork and clone the repository
2. Create a feature branch: `git checkout -b feature/your-feature`
3. Make changes, add tests, update documentation
4. Submit a pull request

### Code Style
- **Python**: Follow PEP 8, use type hints
- **Skills**: YAML frontmatter + markdown body + JSON output format
- **Agents**: Use `build_agent` / `build_agent_with_static` from `_base.py`
- **Routes**: One router per domain in `mail_agent/routes/`

### Areas for Contribution
- **New Skills**: Additional parsing capabilities, integrations
- **UI Improvements**: Dashboard enhancements, mobile support
- **Security**: Webhook signature verification, input sanitization
- **Observability**: Additional tracing/metrics integrations
- **Testing**: Unit tests, integration tests, E2E tests

---

**Built with ❤️ for efficient HR automation and intelligent applicant processing.**
