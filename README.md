# Mail Agent - AI-Powered HR Triage System

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.135+-green.svg)](https://fastapi.tiangolo.com/)
[![Docker](https://img.shields.io/badge/Docker-Ready-blue.svg)](https://www.docker.com/)

An intelligent HR automation system that processes job applications via email, using AI-powered skills to extract data, evaluate completeness, and generate professional responses. Features a modular skills architecture, dynamic per-inbox requirements, and comprehensive audit trails.

## 🚀 Features

### Core Capabilities
- **Intelligent Email Processing**: Automatically parses job application emails and extracts structured data.
- **Dynamic Requirements**: Configurable per-inbox job requirements such as LinkedIn, GitHub, resume, or portfolio.
- **Attachment Management**: Smart classification and storage of resumes, cover letters, and other assets.
- **Automated Triage**: AI-powered evaluation of application completeness.
- **Professional Replies**: Context-aware email responses generated for follow-up communications.
- **State Tracking**: Full audit trail of application progress and communications.

### Technical Features
- **Modular Skills System**: Extensible architecture with deterministic and LLM-powered skills.
- **Real-time Processing**: AgentMail webhook-based email processing.
- **Database Persistence**: Built on SQLAlchemy with support for local SQLite and production databases.
- **Docker Ready**: Containerized deployment with `docker-compose`.
- **API-First Design**: REST endpoints for inbox requirements, applicant state, and file access.
- **OpenAI Integration**: Advanced AI capabilities via OpenRouter.

## 🏗️ System Architecture

### High-Level Flow

```
┌─────────────────┐    ┌───────────┐    ┌─────────────────┐
│   AgentMail     │───▶│   ngrok   │───▶│   Mail Agent    │
│   Webhooks      │    │ (HTTPS)   │    │   FastAPI       │
└─────────────────┘    └───────────┘    └─────────────────┘
                                      │
                                      ▼
                               ┌─────────────────┐
                               │   Orchestrator  │
                               │                 │
                               │ 1. Attachments  │
                               │ 2. Email Parser │
                               │ 3. Data Merge   │
                               │ 4. Triage       │
                               │ 5. Reply Comp.  │
                               └─────────────────┘
                                      │
                                      ▼
                               ┌─────────────────┐
                               │   Database      │
                               │   PostgreSQL    │
                               │                 │
                               │ • Applicants    │
                               │ • Files         │
                               │ • Requirements  │
                               │ • History       │
                               └─────────────────┘
```

### Processing Pipeline

1. **Webhook Reception**: AgentMail sends `message.received` events to `POST /`
2. **Attachment Handler**: Classifies and saves files (resumes, cover letters, other)
3. **Email Parser**: Extracts structured data using AI based on dynamic requirements
4. **Data Merge**: Combines extracted data with attachment metadata
5. **Application Triage**: Evaluates completeness using deterministic validation
6. **Reply Composer**: Generates professional email responses
7. **State Update**: Saves all changes with full audit trail

## 🧠 Skills Architecture

### Skill Types
- **LLM Skills**: AI-powered processing with OpenAI/OpenRouter models
- **Deterministic Skills**: Pure Python code for reliable operations

### Core Skills

| Skill | Type | Purpose | Key Features |
|-------|------|---------|--------------|
| **Email Parser** | LLM | Extracts applicant data from email content | URL extraction, text parsing, dynamic field support |
| **Attachment Handler** | Deterministic | Classifies and saves file attachments | Resume/CV detection, secure storage, metadata tracking |
| **Application Triage** | LLM | Evaluates application completeness | Strict validation, missing field identification |
| **HR Reply Composer** | LLM | Generates professional email responses | Context-aware, dynamic field descriptions, professional tone |
| **Requirement Manager** | Deterministic | Manages per-inbox job requirements | Field validation, schema management, default configurations |

### Skill Execution

```python
# Skills are loaded with YAML frontmatter
skills = load_skills()  # From skills/ directory

# Each skill has defined execution mode
if skill["execution_mode"] == "llm":
    # Executed by AI agent with strict JSON output
    response = agent.run(prompt)
    result = parse_agent_json(response.content)
elif skill["execution_mode"] == "deterministic":
    # Executed as pure Python code
    result = deterministic_function(data)
```

## 🚀 Zero to Hero: Running Locally

This project is designed to run locally with minimal setup. Follow these steps to get the agent processing emails in under 5 minutes.

### 1. Prepare your environment

```bash
git clone <repository-url>
cd mail-agent1
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e .
```

### 2. Create AgentMail credentials

- Sign in to AgentMail.
- Create a new inbox for incoming applications.
- Copy your AgentMail API Key.
- Copy the Inbox ID.
- Save the Webhook Secret if AgentMail provides one.

### 3. Create your `.env` file

Use SQLite for the fastest local setup.
Get your agentmail related keys and inbox from [agentmail.to](https://www.agentmail.to/)

```bash
OPENROUTER_API_KEY=sk-or-v1-...
DATABASE_URL=sqlite:///./test.db
AGENTMAIL_API_KEY=your-agentmail-api-key
INBOX_ID=your-inbox-id
```

> `DATABASE_URL` can be a local SQLite file like `sqlite:///./test.db`, so you do not need PostgreSQL to run locally.

### 4. Initialize the database

```bash
python -c "from main import Base, engine; Base.metadata.create_all(bind=engine)"
```

### 5. Start the FastAPI server in the primary terminal

```bash
uvicorn main:app --reload
```

You should see the app start and confirm the dashboard URL.

### 6. Start `ngrok` in a second terminal

```bash
ngrok http 8000
```

This opens a secure public HTTPS endpoint for AgentMail to call your local app.

### 7. Register the webhook in AgentMail

- Copy the `https://...` URL from `ngrok`.
- Set the webhook target to the root endpoint.
- Example:

```text
https://abcd1234.ngrok.io/
```

- Include a trailing slash if AgentMail requires it.
- Save the webhook.

### 8. Verify local UIs

- Admin Dashboard: `http://localhost:8000/dashboard`
- Bindu Agent interface: `http://localhost:3773`
- FastAPI docs: `http://localhost:8000/docs`

## 🔍 Monitoring & UIs

Use these URLs to verify that the app is running and to inspect health and state.

- `http://localhost:8000/dashboard` — Admin dashboard UI.
- `http://localhost:3773` — Local Bindu agent interface.
- `http://localhost:8000/docs` — FastAPI API documentation.

## 🧪 Testing the System

### E2E test with a real AgentMail email

1. Send an email to the configured AgentMail inbox.
2. Watch the `uvicorn` logs in the primary terminal.
3. Confirm the webhook event and processing output.
4. Open `http://localhost:8000/dashboard` to review state.

### Manual webhook simulation with `curl`

Send a simulated AgentMail webhook payload directly to `POST /`.

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

A successful response looks like:

```json
{
  "status": "processed",
  "applicant_status": "PENDING"
}
```

## 📡 API Documentation

### Webhook Processing

#### `POST /` - AgentMail Webhook
Processes incoming email events from AgentMail.

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
      {
        "filename": "resume.pdf",
        "attachment_id": "att-123"
      }
    ]
  }
}
```

**Response:**
```json
{
  "status": "processed",
  "applicant_status": "PENDING"
}
```

### Applicant Management

#### `GET /applicants` - List Applicants
Query parameters:
- `status` (optional): Filter by status (`PENDING`, `APPROVED`)

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
      "updated_at": "2026-04-17T09:30:00Z"
    }
  ],
  "total": 1
}
```

#### `GET /applicants/{thread_id}` - Get Applicant State
Returns detailed state for a specific applicant thread.

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

#### `POST /requirements/{inbox_id}` - Create Requirements
**Request:**
```json
{
  "required_fields": [
    {
      "name": "linkedin",
      "description": "Your LinkedIn profile URL",
      "field_type": "url"
    },
    {
      "name": "resume",
      "description": "Your resume file",
      "field_type": "file"
    }
  ]
}
```

#### `PUT /requirements/{inbox_id}` - Update Requirements
#### `GET /requirements/{inbox_id}` - Get Requirements
#### `DELETE /requirements/{inbox_id}` - Delete Requirements

### File Management

#### `GET /files/{file_id}` - Download Attachment
Returns the original file with proper headers.

### System Endpoints

#### `GET /skills` - List Available Skills
Returns metadata for all loaded skills.

#### `GET /dashboard` - Admin Dashboard
Serves the HTML admin interface.

## ⚙️ Configuration

### Environment Variables

| Variable | Description | Required | Example |
|----------|-------------|----------|---------|
| `OPENROUTER_API_KEY` | OpenRouter/OpenAI API key for AI processing | Yes | `sk-or-v1-...` |
| `DATABASE_URL` | Database connection URL | Yes | `postgresql://user:pass@host:5432/db` |
| `AGENTMAIL_API_KEY` | AgentMail API key for email processing | Yes | `am-key-...` |
| `INBOX_ID` | AgentMail inbox ID for applications | Yes | `inbox-123` |
| `AGENTMAIL_WEBHOOK_SECRET` | Webhook validation secret | Optional | `secret-123` |
| `BINDU_DEPLOYMENT_URL` | Bindu agent deployment URL | Optional | `http://localhost:3773` |

### Database Configuration

**Local Development (SQLite):**
```bash
DATABASE_URL=sqlite:///./hr_triage.db
```

**Production (PostgreSQL):**
```bash
DATABASE_URL=postgresql://hrtriage:password@localhost:5432/hrtriage_db
```

**Docker Compose:**
```bash
DATABASE_URL=postgresql://hrtriage:hrtriage_password@db:5432/hrtriage_db
```

### Example `.env` File

```bash
# AI Configuration
OPENROUTER_API_KEY=sk-or-v1-your-openrouter-key

# Database
DATABASE_URL=sqlite:///./hr_triage.db

# AgentMail Integration
AGENTMAIL_API_KEY=am-your-agentmail-key
INBOX_ID=inbox-your-inbox-id
AGENTMAIL_WEBHOOK_SECRET=your-webhook-secret

# Bindu Agent (Optional)
BINDU_DEPLOYMENT_URL=http://localhost:3773
```

## 🏗️ Project Structure

```
mail-agent/
├── main.py                 # FastAPI application + webhook orchestrator (698 lines)
├── pyproject.toml          # Dependencies and project configuration
├── skills_loader.py         # Skills loading and management utilities (86 lines)
├── skills/                 # AI skill definitions with YAML frontmatter
│   ├── email-parser.md      # Extracts structured data from emails (92 lines)
│   ├── attachment-handler.md # Deterministic file processing (73 lines)
│   ├── application-triage.md # Evaluates application completeness (72 lines)
│   ├── hr-reply-composer.md # Generates professional responses (91 lines)
│   └── requirement-manager.md # Manages dynamic field requirements (136 lines)
├── static/
│   └── dashboard.html       # Admin dashboard UI (1010 lines)
├── uploads/                 # File storage directory
│   ├── resumes/            # Resume and CV files
│   ├── cover_letters/      # Cover letter attachments
│   └── other/              # Miscellaneous files
├── Dockerfile               # Container build configuration (39 lines)
├── docker-compose.yml      # Multi-service deployment (50 lines)
├── .env                    # Environment variables (create manually)
├── .gitignore              # Git ignore patterns
└── README.md               # This documentation
```

### Database Schema

The system uses SQLAlchemy with the following models:

#### **ApplicantState**
- Tracks application status, extracted data, missing fields
- Fields: `thread_id`, `candidate_email`, `status`, `extracted_data`, `missing_fields`

#### **ApplicantMessageLog** 
- Logs all incoming messages for audit trails
- Fields: `thread_id`, `sender_email`, `message_id`, `raw_text`

#### **ApplicantFile**
- Records attachment metadata and storage paths
- Fields: `thread_id`, `file_type`, `original_filename`, `file_path`

#### **JobRequirement**
- Dynamic per-inbox field configurations
- Fields: `inbox_id`, `required_fields` (JSON)

#### **ApplicantStateHistory**
- Audits all status changes and field updates
- Fields: `thread_id`, `old_status`, `new_status`, `changed_at`

## 🔧 Development Notes

- `DATABASE_URL` can be local SQLite for immediate testing.
- Run `python -c "from main import Base, engine; Base.metadata.create_all(bind=engine)"` after updating the database URL.
- The app ignores webhook events that are not `message.received`.
- The webhook root endpoint is `POST /`.

### Local Development Setup

1. **Quick Start (SQLite):**
   ```bash
   git clone <repository>
   cd mail-agent
   python -m venv .venv
   source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
   pip install -e .
   ```

2. **Environment Configuration:**
   ```bash
   # Create .env file
   echo "DATABASE_URL=sqlite:///./dev.db" > .env
   echo "OPENROUTER_API_KEY=your-key" >> .env
   echo "AGENTMAIL_API_KEY=your-key" >> .env
   echo "INBOX_ID=your-inbox" >> .env
   ```

3. **Database Initialization:**
   ```bash
   python -c "from main import Base, engine; Base.metadata.create_all(bind=engine)"
   ```

4. **Run Development Server:**
   ```bash
   uvicorn main:app --reload --host 0.0.0.0 --port 8000
   ```

### Skills Development

**Adding New Skills:**

1. Create `.md` file in `skills/` directory
2. Add YAML frontmatter:
   ```yaml
   ---
   name: your-skill
   description: Skill description
   license: MIT
   metadata:
     execution-mode: llm  # or deterministic
   ---
   ```
3. Write skill content with JSON output format
4. Skill automatically loaded on restart

**Testing Skills:**
```bash
# List loaded skills
curl http://localhost:8000/skills

# Test individual skill via API
python -c "from main import build_skill_agent; agent = build_skill_agent('email-parser'); print(agent.run('test input'))"
```

### Database Operations

**Reset Database:**
```bash
rm *.db  # SQLite
docker-compose down -v  # Docker
```

**View Data:**
```bash
sqlite3 dev.db "SELECT * FROM applicant_triage;"
```

### Debugging

**Enable Debug Logging:**
```bash
export LOG_LEVEL=DEBUG
uvicorn main:app --reload
```

**Test Webhook Manually:**
```bash
curl -X POST http://localhost:8000/ \\
  -H "Content-Type: application/json" \\
  -d @test_webhook.json
```

**Common Issues:**
- **Database connection**: Verify `DATABASE_URL` format
- **API keys**: Check environment variables are loaded
- **Webhook failures**: Ensure AgentMail can reach your endpoint
- **Skill errors**: Check YAML frontmatter syntax

## 🚀 Deployment

### Docker Compose (Recommended)

The included `docker-compose.yml` provides a complete production-ready setup:

```bash
# Start all services
docker-compose up -d

# View logs
docker-compose logs -f

# Stop services
docker-compose down
```

**Services:**
- **Database**: PostgreSQL 16 with health checks
- **Application**: FastAPI + Bindu agent with automatic builds
- **Volumes**: Persistent data for database and file uploads

**Ports:**
- `8000`: FastAPI API and dashboard
- `3773`: Bindu agent interface
- `5432`: PostgreSQL (internal only)

### Production Deployment

1. **Environment Setup:**
   ```bash
   cp .env.example .env
   # Edit .env with production values
   ```

2. **Database Migration:**
   ```bash
   docker-compose exec agent python -c "from main import Base, engine; Base.metadata.create_all(bind=engine)"
   ```

3. **SSL Configuration:**
   - Use reverse proxy (nginx/caddy) for HTTPS
   - Configure AgentMail webhook with HTTPS URL

4. **Monitoring:**
   - Health check: `GET /health`
   - Metrics: FastAPI built-in monitoring
   - Logs: Structured JSON logging

### Manual Deployment

```bash
# Install dependencies
pip install -e .

# Set environment variables
export DATABASE_URL=postgresql://user:pass@host:5432/db
export OPENROUTER_API_KEY=your-key

# Initialize database
python -c "from main import Base, engine; Base.metadata.create_all(bind=engine)"

# Start application
python -m main
```

## 🤝 Contributing

### Development Workflow

1. **Fork and Clone:**
   ```bash
   git clone <your-fork>
   cd mail-agent
   ```

2. **Set Up Development Environment:**
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -e .
   ```

3. **Create Feature Branch:**
   ```bash
   git checkout -b feature/your-feature
   ```

4. **Make Changes:**
   - Add tests for new features
   - Update documentation
   - Follow existing code style

5. **Test Changes:**
   ```bash
   # Run tests
   python -m pytest
   
   # Test skills
   python -c "from skills_loader import load_skills; print(len(load_skills()))"
   ```

6. **Submit Pull Request:**
   ```bash
   git commit -m 'feat: add your feature'
   git push origin feature/your-feature
   ```

### Code Style

- **Python**: Follow PEP 8, use type hints
- **Skills**: Use YAML frontmatter, JSON output format
- **Documentation**: Update README for API changes
- **Tests**: Add unit tests for new functionality

### Areas for Contribution

- **New Skills**: Additional parsing capabilities, integrations
- **UI Improvements**: Dashboard enhancements, mobile support
- **Performance**: Database optimization, caching
- **Security**: Input validation, rate limiting
- **Documentation**: API docs, deployment guides

---

**Built with ❤️ for efficient HR automation and intelligent applicant processing.**

### Support

- **Issues**: Report bugs via GitHub issues
- **Questions**: Use GitHub discussions
- **Security**: Report security issues privately
