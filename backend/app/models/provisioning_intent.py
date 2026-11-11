from sqlalchemy import CheckConstraint, Column, DateTime, String, func

from app.db.database import Base


class ProvisioningIntent(Base):
    __tablename__ = 'provisioning_intents'

    user_id = Column(String(255), primary_key=True)
    intent_id = Column(String(36), nullable=False, unique=True)
    state = Column(String(16), nullable=False, server_default='pending')
    org_id = Column(String(255))
    organization_name = Column(String(320))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    __table_args__ = (
        CheckConstraint("state IN ('pending', 'org_created', 'completed')"),
        CheckConstraint("state = 'pending' OR org_id IS NOT NULL"),
    )
