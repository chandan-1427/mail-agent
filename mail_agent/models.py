from datetime import datetime, timezone

from sqlalchemy import Integer, Column, String, JSON, DateTime
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class ApplicantState(Base):
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
    approved_at = Column(DateTime(timezone=True), nullable=True)
    stalled_at = Column(DateTime(timezone=True), nullable=True)


class ApplicantMessageLog(Base):
    __tablename__ = "applicant_message_log"
    id = Column(Integer, primary_key=True, autoincrement=True)
    thread_id = Column(String, index=True)
    sender_email = Column(String)
    message_id = Column(String)
    raw_text = Column(String)
    received_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class ApplicantFile(Base):
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
    __tablename__ = "job_requirements"
    id = Column(Integer, primary_key=True, autoincrement=True)
    inbox_id = Column(String, unique=True, index=True, nullable=False)
    required_fields = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class ApplicantStateHistory(Base):
    __tablename__ = "applicant_state_history"
    id = Column(Integer, primary_key=True, autoincrement=True)
    thread_id = Column(String, index=True, nullable=False)
    old_status = Column(String)
    new_status = Column(String)
    old_missing_fields = Column(JSON)
    new_missing_fields = Column(JSON)
    changed_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))