"""
HR Triage Agent - Main Entry Point
A modular email processing system for applicant triage.
"""
import nest_asyncio
import os
import base64
import logging
import threading
import uvicorn

from fastapi import Request, BackgroundTasks

from openinference.instrumentation.agno import AgnoInstrumentor
from opentelemetry import trace as trace_api
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from hindsight_agno import configure

from app.config import (
    HINDSIGHT_API_URL,
    HINDSIGHT_API_KEY,
    LANGFUSE_PUBLIC_KEY,
    LANGFUSE_SECRET_KEY,
    RESUME_DIR,
    COVER_LETTER_DIR,
    OTHER_DIR,
    BINDU_DEPLOYMENT_URL,
)
from app.database import init_db
from skills_loader import load_skills
from app.agents import initialize_agents
from app.email_queue import start_email_queue_processor
from app.api import app
from bindu.penguin.bindufy import bindufy

nest_asyncio.apply()

# ============================================================
# HINDSIGHT CONFIGURATION
# ============================================================
configure(
    hindsight_api_url=HINDSIGHT_API_URL,
    api_key=HINDSIGHT_API_KEY,
)

# ============================================================
# OPENTELEMETRY / LANGFUSE CONFIGURATION
# ============================================================
auth = base64.b64encode(f"{LANGFUSE_PUBLIC_KEY}:{LANGFUSE_SECRET_KEY}".encode()).decode()

tracer = trace_api.get_tracer(__name__)

exporter = OTLPSpanExporter(
    endpoint="https://cloud.langfuse.com/api/public/otel/v1/traces",
    headers={
        "Authorization": f"Basic {auth}",
    },
)

provider = TracerProvider()
provider.add_span_processor(BatchSpanProcessor(exporter))
trace_api.set_tracer_provider(provider)

AgnoInstrumentor().instrument()

# ============================================================
# LOGGING CONFIGURATION
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# ============================================================
# INITIALIZE DIRECTORIES
# ============================================================
os.makedirs(RESUME_DIR, exist_ok=True)
os.makedirs(COVER_LETTER_DIR, exist_ok=True)
os.makedirs(OTHER_DIR, exist_ok=True)

# ============================================================
# INITIALIZE DATABASE
# ============================================================
init_db()

# ============================================================
# LOAD SKILLS
# ============================================================
print("\n📚 Loading skills...")
SKILLS = load_skills()
print(f"   Loaded {len(SKILLS)} skills total\n")

# ============================================================
# INITIALIZE AGENTS
# ============================================================
print("🤖 Building skill-powered agents with multi-model routing...")
agents = initialize_agents(SKILLS)
print("   Agents initialized\n")

# ============================================================
# START EMAIL QUEUE PROCESSOR
# ============================================================
start_email_queue_processor()

# ============================================================
# STORE DEPENDENCIES IN APP STATE
# ============================================================

# Store agents and tracer in app state for dependency injection
app.state.agents = agents
app.state.tracer = tracer
app.state.skills = SKILLS

# ============================================================
# BINDU CONFIGURATION
# ============================================================
bindu_config = {
    "author": "chandandakka2@gmail.com",
    "name": "hr_triage_agent",
    "description": "An HR triage agent that evaluates applicants, extracts required details, manages attachments, and replies with missing requirements.",
    "deployment": {
        "url": BINDU_DEPLOYMENT_URL,
        "expose": True,
    },
    "skills": [],
}


def bindu_handler(messages: list[dict[str, str]]):
    """Handler for Bindu agent interface."""
    latest_message = messages[-1]["content"] if messages else ""

    result = agents["triage"].run(f"""
    You are the HR triage agent.

    Process this incoming request:

    {latest_message}
    """)

    return [
        {
            "role": "assistant",
            "content": result.content,
        }
    ]


# ============================================================
# MAIN ENTRY POINT
# ============================================================
if __name__ == "__main__":
    def start_fastapi():
        print("🚀 Starting on port 8000...")
        print("📊 Dashboard: http://localhost:8000/dashboard")
        uvicorn.run(app, host="0.0.0.0", port=8000)

    # Start FastAPI in background thread
    threading.Thread(target=start_fastapi, daemon=True).start()

    print("🌻 Bindu Agent: http://localhost:3773")

    # Run Bindu in main thread
    bindufy(bindu_config, bindu_handler)
