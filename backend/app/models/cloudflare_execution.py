"""Durable one-shot fence for a provider call and its terminal checkpoint."""
from sqlalchemy import Column, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB

from app.db.database import Base


class CloudflareExecution(Base):
    __tablename__ = "cloudflare_executions"
    attempt_id = Column(String(128), ForeignKey("extraction_attempts.attempt_id", ondelete="CASCADE"), primary_key=True)
    org_id = Column(String(255), nullable=False)
    token_digest = Column(String(64), nullable=False)
    terminal_event = Column(JSONB)
