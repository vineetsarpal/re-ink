"""
API endpoints for Contract management.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
import logging

from app.db.database import get_db
from app.models.contract import Contract
from app.models.party import Party
from app.schemas.contract import (
    ContractCreate,
    ContractUpdate,
    ContractResponse,
    ContractWithParties
)

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/", response_model=ContractResponse, status_code=201)
def create_contract(
    contract_data: ContractCreate,
    db: Session = Depends(get_db)
):
    """
    Create a new contract.

    This endpoint can be used to manually create contracts or
    to finalize contracts after reviewing extracted data.
    """
    try:
        # Check if contract number already exists
        existing = db.query(Contract).filter(
            Contract.contract_number == contract_data.contract_number
        ).first()

        if existing:
            raise HTTPException(
                status_code=400,
                detail=f"Contract with number {contract_data.contract_number} already exists"
            )

        # Create contract
        contract_dict = contract_data.model_dump(exclude={"party_roles"})
        contract = Contract(**contract_dict)

        # Add parties if provided
        if contract_data.party_roles:
            for party_role in contract_data.party_roles:
                party = db.query(Party).filter(Party.id == party_role.party_id).first()
                if party:
                    contract.parties.append(party)
                else:
                    logger.warning(f"Party with ID {party_role.party_id} not found")

        db.add(contract)
        db.commit()
        db.refresh(contract)

        logger.info(f"Contract created: {contract.contract_number}")
        return contract

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating contract: {str(e)}")
        raise HTTPException(status_code=500, detail="Error creating contract")


@router.get("/", response_model=List[ContractResponse])
def list_contracts(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    status: Optional[str] = None,
    contract_type: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    List all contracts with optional filtering and pagination.
    """
    try:
        query = db.query(Contract)

        # Apply filters
        if status:
            query = query.filter(Contract.status == status)
        if contract_type:
            query = query.filter(Contract.contract_type == contract_type)

        # Apply pagination
        contracts = query.offset(skip).limit(limit).all()

        return contracts

    except Exception as e:
        logger.error(f"Error listing contracts: {str(e)}")
        raise HTTPException(status_code=500, detail="Error retrieving contracts")


@router.get("/{contract_id}", response_model=ContractWithParties)
def get_contract(contract_id: int, db: Session = Depends(get_db)):
    """
    Get a specific contract by ID, including associated parties.
    """
    try:
        contract = db.query(Contract).filter(Contract.id == contract_id).first()

        if not contract:
            raise HTTPException(status_code=404, detail="Contract not found")

        return contract

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving contract: {str(e)}")
        raise HTTPException(status_code=500, detail="Error retrieving contract")


@router.put("/{contract_id}", response_model=ContractResponse)
def update_contract(
    contract_id: int,
    contract_update: ContractUpdate,
    db: Session = Depends(get_db)
):
    """
    Update an existing contract.
    """
    try:
        contract = db.query(Contract).filter(Contract.id == contract_id).first()

        if not contract:
            raise HTTPException(status_code=404, detail="Contract not found")

        # Update fields
        update_data = contract_update.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(contract, field, value)

        db.commit()
        db.refresh(contract)

        logger.info(f"Contract updated: {contract.contract_number}")
        return contract

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating contract: {str(e)}")
        raise HTTPException(status_code=500, detail="Error updating contract")


@router.delete("/{contract_id}")
def delete_contract(contract_id: int, db: Session = Depends(get_db)):
    """
    Delete a contract (soft delete by setting is_active=False).
    """
    try:
        contract = db.query(Contract).filter(Contract.id == contract_id).first()

        if not contract:
            raise HTTPException(status_code=404, detail="Contract not found")

        # Soft delete
        contract.is_active = False
        db.commit()

        logger.info(f"Contract deleted: {contract.contract_number}")
        return {"message": "Contract deleted successfully"}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting contract: {str(e)}")
        raise HTTPException(status_code=500, detail="Error deleting contract")


@router.post("/{contract_id}/parties/{party_id}")
def add_party_to_contract(
    contract_id: int,
    party_id: int,
    role: str = Query(..., description="Role of party in this contract"),
    db: Session = Depends(get_db)
):
    """
    Associate a party with a contract.
    """
    try:
        contract = db.query(Contract).filter(Contract.id == contract_id).first()
        party = db.query(Party).filter(Party.id == party_id).first()

        if not contract:
            raise HTTPException(status_code=404, detail="Contract not found")
        if not party:
            raise HTTPException(status_code=404, detail="Party not found")

        # Check if association already exists
        if party in contract.parties:
            raise HTTPException(
                status_code=400,
                detail="Party already associated with this contract"
            )

        contract.parties.append(party)
        db.commit()

        return {"message": "Party added to contract successfully"}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error adding party to contract: {str(e)}")
        raise HTTPException(status_code=500, detail="Error adding party to contract")


@router.delete("/{contract_id}/parties/{party_id}")
def remove_party_from_contract(
    contract_id: int,
    party_id: int,
    db: Session = Depends(get_db)
):
    """
    Remove a party association from a contract.
    """
    try:
        contract = db.query(Contract).filter(Contract.id == contract_id).first()
        party = db.query(Party).filter(Party.id == party_id).first()

        if not contract:
            raise HTTPException(status_code=404, detail="Contract not found")
        if not party:
            raise HTTPException(status_code=404, detail="Party not found")

        if party not in contract.parties:
            raise HTTPException(
                status_code=400,
                detail="Party not associated with this contract"
            )

        contract.parties.remove(party)
        db.commit()

        return {"message": "Party removed from contract successfully"}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error removing party from contract: {str(e)}")
        raise HTTPException(status_code=500, detail="Error removing party from contract")
