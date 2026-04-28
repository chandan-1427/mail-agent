"""
Database models and session management.
"""
from datetime import datetime, timezone
from sqlalchemy import Integer, create_engine, Column, String, JSON, DateTime, text
from sqlalchemy.orm import declarative_base, sessionmaker
from .config import DATABASE_URL

# ============================================================
# DATABASE ENGINE & SESSION
# ============================================================
# Use SQLite as fallback if DATABASE_URL is not set or for development
if not DATABASE_URL or DATABASE_URL.startswith("postgresql"):
    try:
        engine = create_engine(DATABASE_URL)
        # Test connection
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        print("⚠️ PostgreSQL connection failed, falling back to SQLite")
        engine = create_engine("sqlite:///test.db", connect_args={"check_same_thread": False})
else:
    engine = create_engine(DATABASE_URL)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# ============================================================
# DATABASE MODELS
# ============================================================

class ApplicantState(Base):
    """Main applicant triage state."""
    __tablename__ = "applicant_triage"
    id = Column(Integer, primary_key=True, autoincrement=True)
    thread_id = Column(String, unique=True, index=True, nullable=False)
    candidate_email = Column(String, index=True, nullable=False)
    status = Column(String, default="PENDING", nullable=False)
    extracted_data = Column(JSON, default=dict)
    missing_fields = Column(JSON, default=list)
    latest_message = Column(String)
    reply_count = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    approved_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    stalled_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class ApplicantMessageLog(Base):
    """Log of all messages received from applicants."""
    __tablename__ = "applicant_message_log"
    id = Column(Integer, primary_key=True, autoincrement=True)
    thread_id = Column(String, index=True)
    sender_email = Column(String)
    message_id = Column(String)
    raw_text = Column(String)
    received_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class ApplicantFile(Base):
    """Files uploaded by applicants."""
    __tablename__ = "applicant_files"
    id = Column(Integer, primary_key=True, autoincrement=True)
    thread_id = Column(String, index=True, nullable=False)
    candidate_email = Column(String, nullable=False)
    message_id = Column(String, nullable=False)
    file_type = Column(String, nullable=False)
    original_filename = Column(String, nullable=False)
    stored_filename = Column(String, nullable=False)
    file_path = Column(String, nullable=False)
    uploaded_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class JobRequirement(Base):
    """Custom job requirements per inbox."""
    __tablename__ = "job_requirements"
    id = Column(Integer, primary_key=True, autoincrement=True)
    inbox_id = Column(String, unique=True, index=True, nullable=False)
    required_fields = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class ApplicantStateHistory(Base):
    """History of state changes for audit trail."""
    __tablename__ = "applicant_state_history"
    id = Column(Integer, primary_key=True, autoincrement=True)
    thread_id = Column(String, index=True, nullable=False)
    old_status = Column(String)
    new_status = Column(String)
    old_missing_fields = Column(JSON)
    new_missing_fields = Column(JSON)
    changed_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


# Create all tables
def init_db():
    """Initialize database tables."""
    Base.metadata.create_all(bind=engine)
