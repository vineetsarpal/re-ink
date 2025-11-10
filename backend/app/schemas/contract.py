"""
Pydantic schemas for Contract API requests and responses.
"""
from pydantic import BaseModel, condecimal
from typing import Optional, List
from datetime import datetime, date
from decimal import Decimal


class ContractPartyRole(BaseModel):
    """Schema for party-contract association."""
    party_id: int
    role: str


class ContractBase(BaseModel):
    """Base schema with common contract fields."""
    contract_number: str
    contract_name: str
    contract_type: Optional[str] = None
    contract_sub_type: Optional[str] = None
    contract_nature: Optional[str] = None
    effective_date: date
    expiration_date: date
    inception_date: Optional[date] = None
    premium_amount: Optional[Decimal] = None
    currency: str = "USD"
    limit_amount: Optional[Decimal] = None
    retention_amount: Optional[Decimal] = None
    commission_rate: Optional[Decimal] = None
    line_of_business: Optional[str] = None
    coverage_territory: Optional[str] = None
    coverage_description: Optional[str] = None
    terms_and_conditions: Optional[str] = None
    special_provisions: Optional[str] = None
    status: str = "draft"
    notes: Optional[str] = None
    is_active: bool = True


class ContractCreate(ContractBase):
    """Schema for creating a new contract."""
    party_roles: Optional[List[ContractPartyRole]] = []


class ContractUpdate(BaseModel):
    """Schema for updating a contract (all fields optional)."""
    contract_number: Optional[str] = None
    contract_name: Optional[str] = None
    contract_type: Optional[str] = None
    contract_sub_type: Optional[str] = None
    contract_nature: Optional[str] = None
    effective_date: Optional[date] = None
    expiration_date: Optional[date] = None
    inception_date: Optional[date] = None
    premium_amount: Optional[Decimal] = None
    currency: Optional[str] = None
    limit_amount: Optional[Decimal] = None
    retention_amount: Optional[Decimal] = None
    commission_rate: Optional[Decimal] = None
    line_of_business: Optional[str] = None
    coverage_territory: Optional[str] = None
    coverage_description: Optional[str] = None
    terms_and_conditions: Optional[str] = None
    special_provisions: Optional[str] = None
    status: Optional[str] = None
    review_status: Optional[str] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


class ContractResponse(ContractBase):
    """Schema for contract API responses."""
    id: int
    source_document_path: Optional[str] = None
    source_document_name: Optional[str] = None
    review_status: str
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    extraction_confidence: Optional[Decimal] = None
    extraction_job_id: Optional[str] = None
    is_manually_created: bool
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ContractWithParties(ContractResponse):
    """Contract response with associated parties included."""
    parties: List["PartyResponse"] = []

    class Config:
        from_attributes = True


# Import PartyResponse for type hints
from .party import PartyResponse
ContractWithParties.model_rebuild()
