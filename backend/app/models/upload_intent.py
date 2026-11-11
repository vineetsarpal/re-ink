"""Durable lease separating original writes from job creation."""
from sqlalchemy import Column, DateTime, String
from app.db.database import Base


class UploadIntent(Base):
    __tablename__ = "upload_intents"
    job_id = Column(String(100), primary_key=True)
    org_id = Column(String(255), nullable=False)
    storage_key = Column(String(500), nullable=False, unique=True)
    status = Column(String(16), nullable=False)
    lease_deadline = Column(DateTime(timezone=True), nullable=False)
