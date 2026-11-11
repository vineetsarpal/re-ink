from sqlalchemy import CheckConstraint, Column, DateTime, Integer, String, Text

from app.db.database import Base


class OrganizationLifecycle(Base):
    __tablename__ = 'organization_lifecycle'

    org_id = Column(String(255), primary_key=True)
    status = Column(String(16), nullable=False, server_default='active')
    closure_requested_at = Column(DateTime(timezone=True))
    purge_after = Column(DateTime(timezone=True))
    requested_by_hash = Column(String(64))
    purge_step = Column(String(32))
    purge_attempts = Column(Integer, nullable=False, server_default='0')
    last_purge_error = Column(Text)
    __table_args__ = (
        CheckConstraint("status IN ('active', 'closing', 'purged')"),
        CheckConstraint('purge_attempts >= 0'),
        CheckConstraint("status = 'active' OR (closure_requested_at IS NOT NULL AND purge_after IS NOT NULL AND requested_by_hash IS NOT NULL)"),
    )
