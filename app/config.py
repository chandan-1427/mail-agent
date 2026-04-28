"""
Configuration and environment variables for the HR Triage Agent.
"""
import os
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# API KEYS & ENDPOINTS
# ============================================================
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")
AGENTMAIL_API_KEY = os.getenv("AGENTMAIL_API_KEY")
INBOX_ID = os.getenv("INBOX_ID")

# Hindsight Configuration
HINDSIGHT_API_URL = os.getenv("HINDSIGHT_API_URL", "http://localhost:8888")
HINDSIGHT_API_KEY = os.getenv("HINDSIGHT_API_KEY", "")

# Langfuse Configuration
LANGFUSE_PUBLIC_KEY = os.getenv("LANGFUSE_PUBLIC_KEY")
LANGFUSE_SECRET_KEY = os.getenv("LANGFUSE_SECRET_KEY")

# Slack Webhook for escalation
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")

# Webhook signature verification
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")

# Bindu Configuration
BINDU_DEPLOYMENT_URL = os.getenv("BINDU_DEPLOYMENT_URL", "http://localhost:3773")

# ============================================================
# RATE LIMITING CONFIGURATION
# ============================================================
RATE_LIMIT_WINDOW = timedelta(minutes=5)
RATE_LIMIT_MAX_REQUESTS = 10
MAX_REPLIES_PER_THREAD = 5

# ============================================================
# STALLED DETECTION CONFIGURATION
# ============================================================
STALLED_THRESHOLD_DAYS = 7

# ============================================================
# EMAIL QUEUE CONFIGURATION
# ============================================================
MAX_QUEUE_SIZE = 1000

# ============================================================
# FILE UPLOAD DIRECTORIES
# ============================================================
UPLOAD_DIR = "uploads"
RESUME_DIR = os.path.join(UPLOAD_DIR, "resumes")
COVER_LETTER_DIR = os.path.join(UPLOAD_DIR, "cover_letters")
OTHER_DIR = os.path.join(UPLOAD_DIR, "other")

# ============================================================
# SPAM DETECTION KEYWORDS
# ============================================================
SPAM_KEYWORDS = [
    "viagra", "casino", "lottery", "winner", "congratulations",
    "bitcoin", "crypto", "investment opportunity", "nigerian prince",
    "click here", "free money", "urgent", "act now"
]

# ============================================================
# VALIDATION
# ============================================================
if not LANGFUSE_PUBLIC_KEY or not LANGFUSE_SECRET_KEY:
    raise ValueError("Langfuse keys missing")
