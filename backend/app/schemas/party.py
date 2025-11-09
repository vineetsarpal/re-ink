"""
Pydantic schemas for Party API requests and responses.
"""
from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime


class PartyBase(BaseModel):
    """Base schema with common party fields."""
    name: str
    party_type: str
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
    party_type: Optional[str] = None
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
