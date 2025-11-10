"""
Contract model representing reinsurance contracts with associated parties and documents.
"""
from sqlalchemy import (
    Column, Integer, String, DateTime, Text, Numeric,
    Date, Boolean, ForeignKey, Table
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.database import Base


# Association table for many-to-many relationship between contracts and parties
contract_parties = Table(
    'contract_parties',
    Base.metadata,
    Column('contract_id', Integer, ForeignKey('contracts.id'), primary_key=True),
    Column('party_id', Integer, ForeignKey('parties.id'), primary_key=True),
    Column('role', String(50)),  # Role of party in this contract (e.g., "cedent", "reinsurer")
    Column('created_at', DateTime(timezone=True), server_default=func.now())
)


class Contract(Base):
    """
    Contract entity representing a reinsurance contract with all relevant details.
    """
    __tablename__ = "contracts"

    id = Column(Integer, primary_key=True, index=True)

    # Contract Identification
    contract_number = Column(String(100), unique=True, nullable=False, index=True)
    contract_name = Column(String(255), nullable=False)
    contract_type = Column(String(50))  # treaty, facultative
    contract_sub_type = Column(String(100))  # quota_share, surplus, xol, facultative_obligatory, facultative_optional
    contract_nature = Column(String(50))  # proportional, non-proportional

    # Contract Dates
    effective_date = Column(Date, nullable=False)
    expiration_date = Column(Date, nullable=False)
    inception_date = Column(Date)

    # Financial Terms
    premium_amount = Column(Numeric(precision=15, scale=2))
    currency = Column(String(3), default="USD")  # ISO 4217 currency code
    limit_amount = Column(Numeric(precision=15, scale=2))
    retention_amount = Column(Numeric(precision=15, scale=2))
    commission_rate = Column(Numeric(precision=5, scale=2))  # Percentage

    # Coverage Details
    line_of_business = Column(String(100))  # property, casualty, health, etc.
    coverage_territory = Column(String(255))  # Geographic coverage
    coverage_description = Column(Text)

    # Contract Terms
    terms_and_conditions = Column(Text)
    special_provisions = Column(Text)

    # Document Management
    source_document_path = Column(String(500))  # Path to original uploaded document
    source_document_name = Column(String(255))

    # Status and Workflow
    status = Column(String(50), default="draft")  # draft, pending_review, active, expired, cancelled
    review_status = Column(String(50), default="pending")  # pending, approved, rejected
    reviewed_by = Column(String(100))  # User who reviewed
    reviewed_at = Column(DateTime(timezone=True))

    # Extraction Metadata
    extraction_confidence = Column(Numeric(precision=5, scale=2))  # AI confidence score
    extraction_job_id = Column(String(100))  # LandingAI job ID for tracking
    is_manually_created = Column(Boolean, default=False)

    # Additional Information
    notes = Column(Text)
    is_active = Column(Boolean, default=True)

    # Metadata
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    parties = relationship(
        "Party",
        secondary=contract_parties,
        backref="contracts"
    )

    def __repr__(self):
        return f"<Contract(id={self.id}, number='{self.contract_number}', name='{self.contract_name}')>"
