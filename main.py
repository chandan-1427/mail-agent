import os
import uvicorn
import json
from datetime import datetime, timezone
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from agno.agent import Agent
from agno.models.openai import OpenAIChat

# Database imports
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, JSON
from sqlalchemy.orm import declarative_base, sessionmaker

load_dotenv()

# 1. Setup API Keys & Database
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")

# 2. Database Configuration & Schema
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class EmailAuditLog(Base):
    """Schema for storing agent and email interactions"""
    __tablename__ = "email_audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    sender = Column(String, index=True)
    subject = Column(String)
    raw_payload = Column(JSON)       # Stores the complete raw webhook data
    agent_prompt = Column(Text)      # The prompt we sent to the LLM
    agent_response = Column(Text)    # The LLM's formatted markdown response

# Automatically create the table if it doesn't exist
Base.metadata.create_all(bind=engine)

# 3. Configure the Agno Agent (v2.5)
email_agent = Agent(
    name="HR Triage Assistant",
    model=OpenAIChat(
        id="openai/gpt-4o",
        api_key=OPENROUTER_API_KEY,
        base_url="https://openrouter.ai/api/v1"
    ),
    description="You are an autonomous email assistant tasked with reading and formatting raw email data.",
    instructions=[
        "You will be provided with a raw JSON payload representing a new email.",
        "Extract and clearly display the 'Sender' (from), 'Subject', and 'Message Content' (use 'extracted_text' or 'text').",
        "Format the output cleanly for a terminal reader using Markdown.",
        "Do not invent or hallucinate email contents. Only output what is in the provided JSON."
    ],
    markdown=True,
)

# 4. Set up the Webhook Server
app = FastAPI()

@app.post("/")
async def handle_agentmail_webhook(request: Request):
    """
    This endpoint receives the POST request from AgentMail.
    """
    payload = await request.json()
    
    print("\n" + "="*50)
    print(f"🔔 Webhook triggered! Event type: {payload.get('event_type', 'unknown')}")
    print("Handing over raw email data to the Agno Agent...")
    print("="*50 + "\n")
    
    if payload.get("event_type") == "message.received":
        prompt = f"""
        A new email just arrived! Here is the raw webhook data:
        
        {json.dumps(payload, indent=2)}
        
        Please read this JSON and display the sender, subject, and full content.
        """
        
        # 1. Run the agent and capture the response object
        run_response = email_agent.run(prompt)
        agent_output = run_response.content
        
        # 2. Print the response to the terminal
        print(agent_output)
        
        # 3. Save everything to PostgreSQL
        message_data = payload.get("message", {})
        db = SessionLocal()
        
        try:
            log_entry = EmailAuditLog(
                sender=message_data.get("from", "unknown_sender"),
                subject=message_data.get("subject", "No Subject"),
                raw_payload=payload,
                agent_prompt=prompt,
                agent_response=agent_output
            )
            db.add(log_entry)
            db.commit()
            print("\n✅ Audit log successfully saved to PostgreSQL.")
        except Exception as e:
            print(f"\n❌ Error saving to database: {e}")
            db.rollback()
        finally:
            db.close()
            
    else:
        print("Received a different event type, skipping agent processing.")
    
    return {"status": "received"}

# 5. Run the Server
if __name__ == "__main__":
    print("Starting Webhook Server on port 8000...")
    uvicorn.run(app, host="0.0.0.0", port=8000)