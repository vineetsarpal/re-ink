"""
Pydantic schemas for Party API requests and responses.
"""
from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import datetime


class PartyBase(BaseModel):
    """Base schema with common party fields."""
    name: str
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    address_line1: Optional[str] = None
    address_line2: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    postal_code: Optional[str] = None
    country: Optional[str] = None
    registration_number: Optional[str] = None
    license_number: Optional[str] = None
    notes: Optional[str] = None
    is_active: bool = True


class PartyCreate(PartyBase):
    """Schema for creating a new party."""
    pass


class PartyUpdate(BaseModel):
    """Schema for updating a party (all fields optional)."""
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    address_line1: Optional[str] = None
    address_line2: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    postal_code: Optional[str] = None
    country: Optional[str] = None
    registration_number: Optional[str] = None
    license_number: Optional[str] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


class PartyResponse(PartyBase):
    """Schema for party API responses."""
    id: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True  # Allows creation from ORM models


# --- Party matching schemas ---


class PartyMatchRequest(BaseModel):
    """Request to find fuzzy matches for extracted party names."""
    names: List[str]
    threshold: float = 60.0  # minimum score (0-100) to include


class PartyMatchCandidate(BaseModel):
    """A single match candidate for a party name."""
    party_id: int
    party_name: str
    score: float  # 0-100

    class Config:
        from_attributes = True


class PartyMatchResult(BaseModel):
    """Match results for one extracted name."""
    extracted_name: str
    candidates: List[PartyMatchCandidate]


class PartyAction(BaseModel):
    """Per-party instruction: link to existing or create new, plus the role the
    party plays *on this specific contract* (cedant, reinsurer, broker, etc.)."""
    action: str  # "use_existing" or "create_new"
    role: Optional[str] = None  # Role on the contract being approved
    existing_party_id: Optional[int] = None
    party_data: Optional[PartyCreate] = None


class PartyWithRoleResponse(PartyResponse):
    """A party response enriched with its role on a specific contract."""
    role: Optional[str] = None
