"""
main.py

FastAPI application - entry point.
All business logic lives in orchestrator.py and agents/*.
Routes are modularized in the routes/ directory.
"""

import os
import logging
from dotenv import load_dotenv
from fastapi import FastAPI

from mail_agent.database import init_db
from mail_agent.utils import RESUME_DIR, COVER_LETTER_DIR, OTHER_DIR

# Import the bundled routers from the routes package
from mail_agent.routes import (
    applicants_router,
    requirements_router,
    webhook_router,
    misc_router,
)

load_dotenv()

# ── config ────────────────────────────────────────────────────────────────────

# Ensure upload directories exist
for _d in [RESUME_DIR, COVER_LETTER_DIR, OTHER_DIR]:
    os.makedirs(_d, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# Initialize the database tables
init_db()

# ── app ───────────────────────────────────────────────────────────────────────

app = FastAPI(title="HR Triage Agent")

# ── register routes ───────────────────────────────────────────────────────────

app.include_router(webhook_router)
app.include_router(applicants_router)
app.include_router(requirements_router)
app.include_router(misc_router)

# ── entrypoint ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    print("🚀 Starting on http://0.0.0.0:8000")
    print("📊 Dashboard: http://localhost:8000/dashboard")
    
    # Passing the app as a string allows uvicorn to support hot-reloading if desired
    uvicorn.run("mail_agent.main:app", host="0.0.0.0", port=8000)