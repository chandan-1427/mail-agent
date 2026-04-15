"""
HR Triage Agent with AgentMail Integration without subagent architecture.
This implementation focuses on a single, stateful agent that handles the entire triage process for job applicants.
The agent receives incoming emails, extracts relevant information, updates the applicant's state in the database, and drafts replies—all within one cohesive workflow.  
"""

# import os
# import uvicorn
# import json
# from datetime import datetime, timezone
# from dotenv import load_dotenv
# from fastapi import FastAPI, HTTPException, Request
# from fastapi.responses import FileResponse
# from pydantic import BaseModel, Field

# # Database imports
# from sqlalchemy import Integer, create_engine, Column, String, JSON, DateTime
# from sqlalchemy.orm import declarative_base, sessionmaker

# from agno.agent import Agent
# from agno.models.openai import OpenAIChat
# from agentmail import AgentMail

# load_dotenv()

# # 1. Setup Environment
# OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
# DATABASE_URL = os.getenv("DATABASE_URL")
# AGENTMAIL_API_KEY = os.getenv("AGENTMAIL_API_KEY")
# INBOX_ID = os.getenv("INBOX_ID") # Crucial for loop prevention

# # 2. Database Configuration & State Schema
# engine = create_engine(DATABASE_URL)
# SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
# Base = declarative_base()

# UPLOAD_DIR = "uploads"
# RESUME_DIR = os.path.join(UPLOAD_DIR, "resumes")
# COVER_LETTER_DIR = os.path.join(UPLOAD_DIR, "cover_letters")
# OTHER_DIR = os.path.join(UPLOAD_DIR, "other")

# os.makedirs(RESUME_DIR, exist_ok=True)
# os.makedirs(COVER_LETTER_DIR, exist_ok=True)
# os.makedirs(OTHER_DIR, exist_ok=True)

# class ApplicantState(Base):
#     __tablename__ = "applicant_triage"

#     id = Column(Integer, primary_key=True, autoincrement=True)
#     thread_id = Column(String, unique=True, index=True, nullable=False)
#     candidate_email = Column(String, index=True, nullable=False)
#     status = Column(String, default="PENDING", nullable=False)
#     extracted_data = Column(JSON, default=dict)
#     missing_fields = Column(JSON, default=list)
#     latest_message = Column(String)
#     reply_count = Column(Integer, default=0)
#     created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
#     updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
#     approved_at = Column(DateTime, nullable=True)
    
# class ApplicantMessageLog(Base):
#     __tablename__ = "applicant_message_log"

#     id = Column(Integer, primary_key=True, autoincrement=True)
#     thread_id = Column(String, index=True)
#     sender_email = Column(String)
#     message_id = Column(String)
#     raw_text = Column(String)
#     received_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    
# # 3. Pydantic Structured Output
# class TriageResult(BaseModel):
#     """Forces the LLM to output predictable, parseable data."""
#     is_approved: bool = Field(description="True ONLY if linkedin, github, and resume are all provided.")
#     extracted_data: dict = Field(description="Dictionary of data found so far.")
#     missing_fields: list[str] = Field(description="List of fields still required.")
#     reply_draft: str | None = Field(description="If NOT approved, draft a polite reply asking for the missing fields. If approved, draft a quick thank-you email.")

# class ApplicantFile(Base):
#     __tablename__ = "applicant_files"

#     id = Column(Integer, primary_key=True, autoincrement=True)
#     thread_id = Column(String, index=True, nullable=False)
#     candidate_email = Column(String, nullable=False)
#     message_id = Column(String, nullable=False)
#     file_type = Column(String, nullable=False)  # resume, cover_letter, other
#     original_filename = Column(String, nullable=False)
#     stored_filename = Column(String, nullable=False)
#     file_path = Column(String, nullable=False)
#     uploaded_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    
# class JobRequirement(Base):
#     __tablename__ = "job_requirements"

#     id = Column(Integer, primary_key=True, autoincrement=True)
#     inbox_id = Column(String, unique=True, index=True, nullable=False)
#     required_fields = Column(JSON, nullable=False)
#     created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    
# class ApplicantStateHistory(Base):
#     __tablename__ = "applicant_state_history"

#     id = Column(Integer, primary_key=True, autoincrement=True)
#     thread_id = Column(String, index=True, nullable=False)
#     old_status = Column(String)
#     new_status = Column(String)
#     old_missing_fields = Column(JSON)
#     new_missing_fields = Column(JSON)
#     changed_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    
# Base.metadata.create_all(bind=engine)

# # 4. Configure the Stateful Agno Agent
# email_agent = Agent(
#     name="HR Triage Assistant",
#     model=OpenAIChat(
#         id="openai/gpt-4o",
#         api_key=OPENROUTER_API_KEY,
#         base_url="https://openrouter.ai/api/v1"
#     ),
#     description="You are an autonomous HR triage agent validating software engineering applicants.",
#     instructions=[
#         "You will be given the candidate's existing database state and their newest email.",
#         "Your objective is to collect their LinkedIn, GitHub, and Resume.",
#         "Update the extracted data and determine what is still missing.",
#         "Return ONLY valid JSON in this exact format:",
#         """
#         {
#           "is_approved": true,
#           "extracted_data": {
#             "linkedin": "",
#             "github": "",
#             "resume": ""
#           },
#           "missing_fields": [],
#           "reply_draft": ""
#         }
#         """,
#         "Return ONLY raw JSON.",
#         "Do not wrap the JSON in markdown code fences.",
#         "Do not use ```json."
#     ],
#     markdown=False,
# )

# # 5. Initialize the AgentMail Client for Replies
# agentmail_client = AgentMail(api_key=AGENTMAIL_API_KEY)

# # 6. Webhook Execution Pipeline
# app = FastAPI()

# @app.post("/")
# async def handle_agentmail_webhook(request: Request):
#     payload = await request.json()
    
#     # Ignore non-message events
#     if payload.get("event_type") != "message.received":
#         return {"status": "ignored"}
        
#     message_data = payload.get("message", {})
#     sender = message_data.get("from_", "")
#     thread_id = message_data.get("thread_id")
#     inbox_id = message_data.get("inbox_id")
#     message_id = message_data.get("message_id")
#     raw_text = message_data.get("text", "")
#     attachments = message_data.get("attachments", [])
    
#     db = SessionLocal()
        
#     saved_files = {}
    
#     for attachment in attachments:
#       original_filename = attachment.get("filename")
#       attachment_id = attachment.get("attachment_id")

#       if not original_filename or not attachment_id:
#           continue

#       lower_filename = original_filename.lower()

#       if any(keyword in lower_filename for keyword in ["resume", "cv"]):
#           file_type = "resume"
#           save_dir = RESUME_DIR
#       elif "cover" in lower_filename:
#           file_type = "cover_letter"
#           save_dir = COVER_LETTER_DIR
#       else:
#           file_type = "other"
#           save_dir = OTHER_DIR

#       stored_filename = f"{thread_id}_{attachment_id}_{original_filename}"
#       file_path = os.path.join(save_dir, stored_filename)
#       saved_files[file_type] = file_path
      
#       try:
#           attachment_response = agentmail_client.inboxes.messages.get_attachment(
#               inbox_id=inbox_id,
#               message_id=message_id,
#               attachment_id=attachment_id
#           )

#           download_url = getattr(attachment_response, "download_url", None)

#           if not download_url and isinstance(attachment_response, dict):
#               download_url = attachment_response.get("download_url")

#           if download_url:
#               import urllib.request

#               with urllib.request.urlopen(download_url) as response:
#                   file_bytes = response.read()

#               with open(file_path, "wb") as f:
#                   f.write(file_bytes)

#               file_record = ApplicantFile(
#                   thread_id=thread_id,
#                   candidate_email=sender,
#                   message_id=message_id,
#                   file_type=file_type,
#                   original_filename=original_filename,
#                   stored_filename=stored_filename,
#                   file_path=file_path,
#               )

#               db.add(file_record)

#       except Exception as e:
#           print(f"Failed to save attachment {original_filename}: {e}")
        
#     message_log = ApplicantMessageLog(
#         thread_id=thread_id,
#         sender_email=sender,
#         message_id=message_id,
#         raw_text=raw_text,
#     )

#     db.add(message_log)
    
#     # GUARD: Prevent the agent from replying to its own sent emails
#     if INBOX_ID and INBOX_ID in sender:
#         print("Self-sent message detected. Ignoring to prevent loop.")
#         return {"status": "ignored"}

#     try:
#         # Step 1: Retrieve or Create Thread State
#         state = db.query(ApplicantState).filter(ApplicantState.thread_id == thread_id).first()
        
#         if not state:
#             state = ApplicantState(
#                 thread_id=thread_id,
#                 candidate_email=sender,
#                 missing_fields=["linkedin", "github", "resume"],
#                 extracted_data={}
#             )
#             db.add(state)
#             db.commit() # Commit so it exists in DB for this run
            
#         # Ignore threads that are already completely approved
#         if state.status == "APPROVED" and len(state.missing_fields or []) == 0:
#             print(f"Thread {thread_id} already approved. Skipping.")
#             return {"status": "ignored"}
            
#         # Step 2: Construct Contextual Prompt (Now including attachments!)
#         attached_file_types = list(saved_files.keys())
        
#         prompt = f"""
#         Candidate Email: {sender}
#         Current Extracted Data: {json.dumps(state.extracted_data)}
#         Currently Missing Fields: {json.dumps(state.missing_fields)}
#         Attached Files in this email: {json.dumps(attached_file_types)}
        
#         New Message Content:
#         {raw_text}
        
#         Analyze the new message and the attached files, merge the data, and generate the triage response.
#         """
        
#         # Step 3: Run Agent
#         print("\nAnalyzing message state...")
#         run_response = email_agent.run(prompt)
        
#         raw_content = run_response.content

#         cleaned_content = raw_content.strip()

#         if cleaned_content.startswith("```json"):
#             cleaned_content = cleaned_content.replace("```json", "", 1)

#         if cleaned_content.startswith("```"):
#             cleaned_content = cleaned_content.replace("```", "", 1)

#         if cleaned_content.endswith("```"):
#             cleaned_content = cleaned_content[:-3]

#         cleaned_content = cleaned_content.strip()

#         result = json.loads(cleaned_content)

#         print("\nStructured Agent Output:")
#         print(json.dumps(result, indent=2))

#         # Step 4: Update Database State safely
#         # Merge old extracted data with newly found data
#         current_extracted = state.extracted_data or {}

#         # First merge uploaded files
#         for key, value in saved_files.items():
#             current_extracted[key] = value

#         # Then merge LLM extracted values
#         for key, value in result.get("extracted_data", {}).items():
#             if value:
#                 current_extracted[key] = value

#         # Merge previous state + uploaded files + new LLM extraction
#         existing_data = state.extracted_data or {}

#         for key, value in existing_data.items():
#             if value and key not in current_extracted:
#                 current_extracted[key] = value

#         state.extracted_data = current_extracted
        
#         job_requirement = (
#             db.query(JobRequirement)
#             .filter(JobRequirement.inbox_id == inbox_id)
#             .first()
#         )

#         required_fields = (
#             job_requirement.required_fields
#             if job_requirement
#             else ["linkedin", "github", "resume"]
#         )

#         missing_fields = []

#         for field in required_fields:
#             value = state.extracted_data.get(field)

#             if value is None:
#                 missing_fields.append(field)
#                 continue

#             if isinstance(value, str) and not value.strip():
#                 missing_fields.append(field)
#                 continue

#         state.missing_fields = missing_fields
#         state.latest_message = raw_text
#         state.reply_count = (state.reply_count or 0) + 1
#         state.updated_at = datetime.now(timezone.utc)

#         if len(missing_fields) == 0:
#             state.status = "APPROVED"
#             state.missing_fields = []
#             state.approved_at = datetime.now(timezone.utc)
#         else:
#             state.status = "PENDING"
#             state.missing_fields = missing_fields
#             state.approved_at = None
            
#         db.add(message_log)
#         db.commit()
        
#         # Step 5: Reply to the Candidate using AgentMail SDK
#         if result.get("reply_draft"):
#             print(f"Status: {state.status}. Sending reply to {sender}...")
#             reply_text = result.get("reply_draft", "")

#             if state.status == "PENDING":
#                 missing_text = "\n".join([f"- {field}" for field in missing_fields])

#                 reply_text = f"""
#             Thank you for your application.

#             We still need the following details to continue your application:

#             {missing_text}

#             Please reply with the missing details.
#             """

#             agentmail_client.inboxes.messages.reply(
#                 inbox_id=inbox_id,
#                 message_id=message_id,
#                 text=reply_text
#             )
            
#         print("\n✅ Triage cycle complete.")
            
#     except Exception as e:
#         print(f"\n❌ Error processing webhook: {e}")
#         db.rollback()
#     finally:
#         db.close()
        
#     return {"status": "processed"}

# @app.get("/files/{file_id}")
# def get_file(file_id: int):
#     db = SessionLocal()

#     file_record = db.query(ApplicantFile).filter(ApplicantFile.id == file_id).first()

#     if not file_record:
#         raise HTTPException(status_code=404, detail="File not found")

#     return FileResponse(
#         path=file_record.file_path,
#         filename=file_record.original_filename,
#         media_type="application/octet-stream"
#     )
    
# if __name__ == "__main__":
#     print("Starting Triage Webhook Server on port 8000...")
#     uvicorn.run(app, host="0.0.0.0", port=8000)
