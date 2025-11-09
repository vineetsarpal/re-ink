"""
API endpoints for Party management.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
import logging

from app.db.database import get_db
from app.models.party import Party
from app.schemas.party import PartyCreate, PartyUpdate, PartyResponse

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/", response_model=PartyResponse, status_code=201)
def create_party(
    party_data: PartyCreate,
    db: Session = Depends(get_db)
):
    """
    Create a new party (cedent, reinsurer, broker, etc.).
    """
    try:
        # Check if party with same registration number already exists
        if party_data.registration_number:
            existing = db.query(Party).filter(
                Party.registration_number == party_data.registration_number
            ).first()

            if existing:
                raise HTTPException(
                    status_code=400,
                    detail=f"Party with registration number {party_data.registration_number} already exists"
                )

        # Create party
        party = Party(**party_data.model_dump())
        db.add(party)
        db.commit()
        db.refresh(party)

        logger.info(f"Party created: {party.name}")
        return party

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating party: {str(e)}")
        raise HTTPException(status_code=500, detail="Error creating party")


@router.get("/", response_model=List[PartyResponse])
def list_parties(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    party_type: Optional[str] = None,
    is_active: Optional[bool] = None,
    db: Session = Depends(get_db)
):
    """
    List all parties with optional filtering and pagination.
    """
    try:
        query = db.query(Party)

        # Apply filters
        if party_type:
            query = query.filter(Party.party_type == party_type)
        if is_active is not None:
            query = query.filter(Party.is_active == is_active)

        # Apply pagination
        parties = query.offset(skip).limit(limit).all()

        return parties

    except Exception as e:
        logger.error(f"Error listing parties: {str(e)}")
        raise HTTPException(status_code=500, detail="Error retrieving parties")


@router.get("/{party_id}", response_model=PartyResponse)
def get_party(party_id: int, db: Session = Depends(get_db)):
    """
    Get a specific party by ID.
    """
    try:
        party = db.query(Party).filter(Party.id == party_id).first()

        if not party:
            raise HTTPException(status_code=404, detail="Party not found")

        return party

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving party: {str(e)}")
        raise HTTPException(status_code=500, detail="Error retrieving party")


@router.get("/search/by-name")
def search_parties_by_name(
    name: str = Query(..., min_length=2),
    db: Session = Depends(get_db)
):
    """
    Search for parties by name (case-insensitive partial match).
    """
    try:
        parties = db.query(Party).filter(
            Party.name.ilike(f"%{name}%")
        ).all()

        return parties

    except Exception as e:
        logger.error(f"Error searching parties: {str(e)}")
        raise HTTPException(status_code=500, detail="Error searching parties")


@router.put("/{party_id}", response_model=PartyResponse)
def update_party(
    party_id: int,
    party_update: PartyUpdate,
    db: Session = Depends(get_db)
):
    """
    Update an existing party.
    """
    try:
        party = db.query(Party).filter(Party.id == party_id).first()

        if not party:
            raise HTTPException(status_code=404, detail="Party not found")

        # Update fields
        update_data = party_update.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(party, field, value)

        db.commit()
        db.refresh(party)

        logger.info(f"Party updated: {party.name}")
        return party

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating party: {str(e)}")
        raise HTTPException(status_code=500, detail="Error updating party")


@router.delete("/{party_id}")
def delete_party(party_id: int, db: Session = Depends(get_db)):
    """
    Delete a party (soft delete by setting is_active=False).
    """
    try:
        party = db.query(Party).filter(Party.id == party_id).first()

        if not party:
            raise HTTPException(status_code=404, detail="Party not found")

        # Soft delete
        party.is_active = False
        db.commit()

        logger.info(f"Party deleted: {party.name}")
        return {"message": "Party deleted successfully"}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting party: {str(e)}")
        raise HTTPException(status_code=500, detail="Error deleting party")
