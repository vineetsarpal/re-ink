"""
Party model representing a party (individual or organization) in reinsurance contracts.
"""
from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.database import Base


class Party(Base):
    """
    Party entity representing an individual or organization involved in reinsurance.
    Can be a cedent, reinsurer, broker, or other party type.
    """
    __tablename__ = "parties"

    id = Column(Integer, primary_key=True, index=True)

    # Basic Information
    name = Column(String(255), nullable=False, index=True)
    party_type = Column(String(50), nullable=False)  # cedent, reinsurer, broker, etc.

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
    registration_number = Column(String(100), unique=True)  # Company registration or tax ID
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
        return f"<Party(id={self.id}, name='{self.name}', type='{self.party_type}')>"
