"""Durable extraction attempts, transport leases, callback receipts and cleanup."""
from sqlalchemy import Column, String, Integer, DateTime, Text, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from app.db.database import Base


class ExtractionAttempt(Base):
    __tablename__ = "extraction_attempts"
    attempt_id = Column(String(128), primary_key=True)
    job_id = Column(String(100), ForeignKey("extraction_jobs.job_id"), nullable=False)
    org_id = Column(String(255), nullable=False)
    number = Column(Integer, nullable=False)
    status = Column(String(20), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)
    deadline_at = Column(DateTime(timezone=True), nullable=False)
    accepted_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    execution_key = Column(String(128))
    workflow_execution_id = Column(String(128))
    error_code = Column(String(100))
    error_message = Column(Text)
    __table_args__ = (UniqueConstraint("job_id", "number"),)


class WorkflowOutbox(Base):
    __tablename__ = "workflow_outbox"
    attempt_id = Column(String(128), ForeignKey("extraction_attempts.attempt_id"), primary_key=True)
    org_id = Column(String(255), nullable=False)
    payload = Column(JSONB, nullable=False)
    next_delivery_at = Column(DateTime(timezone=True), nullable=False)
    lease_token = Column(String(128))
    lease_until = Column(DateTime(timezone=True))
    delivery_count = Column(Integer, nullable=False, default=0)
    acknowledged_at = Column(DateTime(timezone=True))
    last_error = Column(String(100))


class WorkflowReceipt(Base):
    __tablename__ = "workflow_receipts"
    attempt_id = Column(String(128), ForeignKey("extraction_attempts.attempt_id"), primary_key=True)
    event_id = Column(String(128), primary_key=True)
    org_id = Column(String(255), nullable=False)
    digest = Column(String(64), nullable=False)
    acknowledgement = Column(JSONB, nullable=False)


class StorageCleanup(Base):
    __tablename__ = "storage_cleanup"
    cleanup_id = Column(String(128), primary_key=True)
    org_id = Column(String(255), nullable=False)
    storage_key = Column(String(500), nullable=False)
    job_id = Column(String(100))
    next_attempt_at = Column(DateTime(timezone=True), nullable=False)
    attempts = Column(Integer, nullable=False, default=0)
    completed_at = Column(DateTime(timezone=True))
    lease_token = Column(String(128))
    lease_until = Column(DateTime(timezone=True))
