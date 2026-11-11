"""Organization-level acknowledgement of external provider processing."""
from sqlalchemy import Column, DateTime, String, func

from app.db.database import Base

LANDINGAI_NOTICE_VERSION = "landingai-processing-v1"


class ProviderAcknowledgment(Base):
    __tablename__ = "provider_acknowledgments"

    org_id = Column(String(255), primary_key=True)
    provider = Column(String(32), primary_key=True)
    notice_version = Column(String(64), nullable=False)
    acknowledged_by = Column(String(255), nullable=False)
    acknowledged_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
