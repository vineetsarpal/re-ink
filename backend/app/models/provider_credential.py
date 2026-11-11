"""Encrypted organization-owned provider credentials."""
from sqlalchemy import Column, DateTime, LargeBinary, String, func

from app.db.database import Base


class ProviderCredential(Base):
    __tablename__ = "provider_credentials"

    org_id = Column(String(255), primary_key=True)
    provider = Column(String(32), primary_key=True)
    ciphertext = Column(LargeBinary, nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
