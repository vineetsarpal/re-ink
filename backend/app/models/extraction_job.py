"""
ExtractionJob model for persisting document extraction job state.
Replaces the in-memory dict so jobs survive across workers and restarts.
"""
from sqlalchemy import Column, String, DateTime, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from app.db.database import Base


class ExtractionJob(Base):
    __tablename__ = "extraction_jobs"

    job_id = Column(String(100), primary_key=True, index=True)
    status = Column(String(20), nullable=False, default="processing")  # processing, completed, failed
    filename = Column(String(255))
    file_path = Column(String(500))
    message = Column(Text)
    landingai_job_id = Column(String(100))
    raw_results = Column(JSONB)
    parsed_results = Column(JSONB)
    error = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True))
    failed_at = Column(DateTime(timezone=True))
