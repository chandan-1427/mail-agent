"""
main.py

FastAPI application - entry point.
All business logic lives in orchestrator.py and agents/*.
Routes are modularized in the routes/ directory.
"""

import os
import base64
import logging
from dotenv import load_dotenv
from fastapi import FastAPI

from opentelemetry import trace as trace_api
from opentelemetry.sdk.trace import TracerProvider

from mail_agent.database import init_db
from mail_agent.utils import RESUME_DIR, COVER_LETTER_DIR, OTHER_DIR

from mail_agent.routes import (
    applicants_router,
    requirements_router,
    webhook_router,
    misc_router,
)

load_dotenv()

for _d in [RESUME_DIR, COVER_LETTER_DIR, OTHER_DIR]:
    os.makedirs(_d, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

def _setup_tracing() -> None:
    """
    Set up Langfuse/OTel tracing exactly once.
    Guard prevents double-init when uvicorn reloads the module
    in its worker process, which caused:
      - WARNING: Overriding of current TracerProvider is not allowed
      - WARNING: Attempting to instrument while already instrumented
    """
    if isinstance(trace_api.get_tracer_provider(), TracerProvider):
        logger.debug("Tracing already initialized — skipping.")
        return

    PUBLIC = os.getenv("LANGFUSE_PUBLIC_KEY")
    SECRET = os.getenv("LANGFUSE_SECRET_KEY")

    if not PUBLIC or not SECRET:
        logger.info("Langfuse keys not provided — tracing disabled")
        return

    try:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from openinference.instrumentation.agno import AgnoInstrumentor

        auth = base64.b64encode(f"{PUBLIC}:{SECRET}".encode()).decode()

        exporter = OTLPSpanExporter(
            endpoint="https://cloud.langfuse.com/api/public/otel/v1/traces",
            headers={"Authorization": f"Basic {auth}"},
            timeout=30,
        )

        provider = TracerProvider()
        provider.add_span_processor(
            BatchSpanProcessor(
                exporter,
                max_export_batch_size=10,
                export_timeout_millis=30000,
                schedule_delay_millis=2000,
            )
        )
        trace_api.set_tracer_provider(provider)

        AgnoInstrumentor().instrument()

        logger.info("Langfuse tracing initialized")
    except ImportError as e:
        logger.warning(f"Tracing dependencies not installed — skipping: {e}")
    except Exception as e:
        logger.warning(f"Failed to initialize tracing — skipping: {e}")


_setup_tracing()

init_db()

app = FastAPI(title="HR Triage Agent")

app.include_router(webhook_router)
app.include_router(applicants_router)
app.include_router(requirements_router)
app.include_router(misc_router)

if __name__ == "__main__":
    import uvicorn
    
    if os.getenv("BINDU_DEPLOYMENT_URL"):
        from bindu.penguin.bindufy import bindufy
        from agno.agent import Agent
        from mail_agent.agents._base import build_agent
        from mail_agent.database import SessionLocal
        from mail_agent.orchestrator import run as orchestrator_run
        
        agent = build_agent("email-parser", "parser")
        
        config = {
            "author": "hr-automation@example.com",
            "name": "mail_triage_agent",
            "description": "AI-powered HR triage system that processes job applications via email",
            "deployment": {
                "url": os.getenv("BINDU_DEPLOYMENT_URL", "http://localhost:3773"),
                "expose": True,
            },
        }
        
        def handler(messages):
            if not messages:
                return {"status": "error", "message": "No messages provided"}
            
            message = messages[-1]
            required_fields = ["sender", "thread_id", "inbox_id", "message_id", "text"]
            missing_fields = [field for field in required_fields if field not in message]
            
            if missing_fields:
                return {
                    "status": "error", 
                    "message": f"Missing required fields: {', '.join(missing_fields)}"
                }
            
            sender = message["sender"]
            thread_id = message["thread_id"]
            inbox_id = message["inbox_id"]
            message_id = message["message_id"]
            raw_text = message["text"]
            attachments = message.get("attachments", [])
            
            db = SessionLocal()
            
            try:
                result = orchestrator_run(
                    sender=sender,
                    thread_id=thread_id,
                    inbox_id=inbox_id,
                    message_id=message_id,
                    raw_text=raw_text,
                    attachments=attachments,
                    db=db,
                )
                return result
                
            except Exception as e:
                return {"status": "error", "message": str(e)}
            
            finally:
                db.close()
        
        bindufy(config, handler)
    else:
        print("Starting on http://0.0.0.0:8000")
        print("Dashboard: http://localhost:8000/dashboard")
        uvicorn.run("mail_agent.main:app", host="0.0.0.0", port=8000)