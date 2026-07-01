"""
Party model representing a party (individual or organization) in reinsurance contracts.
"""
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.database import Base


class Party(Base):
    """
    Party entity representing an individual or organization involved in reinsurance.
    A Party's role (cedant, reinsurer, broker, etc.) is *per contract* and lives on
    the ``contract_parties`` association table, not here — the same party can act as
    a cedant on one contract and a reinsurer on another.
    """
    __tablename__ = "parties"
    __table_args__ = (
        UniqueConstraint(
            "org_id", "registration_number", name="uq_parties_org_registration_number"
        ),
    )

    id = Column(Integer, primary_key=True)
    org_id = Column(
        String(255),
        nullable=False,
        server_default=text("current_setting('app.current_org', true)"),
    )

    # Basic Information
    name = Column(String(255), nullable=False, index=True)

    # Contact Information
    email = Column(String(255), index=True)
    phone = Column(String(50))
    address_line1 = Column(String(255))
    address_line2 = Column(String(255))
    city = Column(String(100))
    state = Column(String(100))
    postal_code = Column(String(20))
    country = Column(String(100))

    # Business Details
    registration_number = Column(String(100))  # Company registration or tax ID
    license_number = Column(String(100))  # Insurance license number

    # Additional Information
    notes = Column(Text)
    is_active = Column(Boolean, default=True)

    # Metadata
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationship to contracts (many-to-many through association table)
    # This will be defined in contract model

    def __repr__(self):
        return f"<Party(id={self.id}, name='{self.name}')>"
