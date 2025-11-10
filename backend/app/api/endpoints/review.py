"""
API endpoints for reviewing and approving extracted contract data.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import logging

from app.db.database import get_db
from app.models.contract import Contract
from app.models.party import Party
from app.schemas.document import ReviewData, ReviewApprovalResponse

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/approve", response_model=ReviewApprovalResponse)
def approve_extracted_data(
    review_data: ReviewData,
    db: Session = Depends(get_db)
):
    """
    Review and approve extracted contract and party data.

    This endpoint:
    1. Creates or finds parties
    2. Creates the contract
    3. Associates parties with the contract
    4. Returns the created entities
    """
    try:
        logger.info("=== Starting approve_extracted_data ===")
        logger.info(f"Received {len(review_data.parties)} parties")
        logger.info(f"Contract data: {review_data.contract.model_dump()}")

        # Check if contract already exists by contract_number
        existing_contract = None
        if review_data.contract.contract_number:
            existing_contract = db.query(Contract).filter(
                Contract.contract_number == review_data.contract.contract_number
            ).first()

        if existing_contract:
            logger.warning(f"Contract with number {review_data.contract.contract_number} already exists (ID: {existing_contract.id})")
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "duplicate_contract",
                    "message": f"A contract with number '{review_data.contract.contract_number}' already exists",
                    "existing_contract_id": existing_contract.id,
                    "contract_number": review_data.contract.contract_number
                }
            )

        party_ids = []
        party_status = []  # Track which parties are new vs existing

        # Process parties
        for party_data in review_data.parties:
            # Check if party already exists by registration number or name
            existing_party = None

            if party_data.registration_number:
                existing_party = db.query(Party).filter(
                    Party.registration_number == party_data.registration_number
                ).first()

            if not existing_party and party_data.email:
                existing_party = db.query(Party).filter(
                    Party.email == party_data.email
                ).first()

            if existing_party:
                # Use existing party
                logger.info(f"Using existing party: {existing_party.name}")
                party_ids.append(existing_party.id)
                party_status.append({
                    "id": existing_party.id,
                    "name": existing_party.name,
                    "status": "existing"
                })
            elif review_data.create_new_parties:
                # Create new party
                new_party = Party(**party_data.model_dump())
                db.add(new_party)
                db.flush()  # Flush to get the ID without committing
                party_ids.append(new_party.id)
                logger.info(f"Created new party: {new_party.name}")
                party_status.append({
                    "id": new_party.id,
                    "name": new_party.name,
                    "status": "created"
                })
            else:
                raise HTTPException(
                    status_code=400,
                    detail=f"Party {party_data.name} does not exist and create_new_parties is False"
                )

        # Create contract
        contract_dict = review_data.contract.model_dump(exclude={"party_roles"})
        contract = Contract(**contract_dict)

        # Set extraction metadata and status
        contract.review_status = "approved"  # User approved the extraction

        # Determine contract status based on dates
        from datetime import date
        today = date.today()

        if contract.expiration_date < today:
            contract.status = "expired"
        elif contract.effective_date <= today <= contract.expiration_date:
            contract.status = "active"
        else:
            # Effective date is in the future
            contract.status = "pending_review"

        contract.is_manually_created = False

        db.add(contract)
        db.flush()

        # Associate parties with contract
        for i, party_id in enumerate(party_ids):
            party = db.query(Party).filter(Party.id == party_id).first()
            if party:
                contract.parties.append(party)

        # Commit all changes
        db.commit()
        db.refresh(contract)

        logger.info(f"Contract approved and created: {contract.contract_number}")

        # Build informative message
        new_parties = [p for p in party_status if p["status"] == "created"]
        existing_parties = [p for p in party_status if p["status"] == "existing"]

        message_parts = [f"Contract created successfully (ID: {contract.id})"]
        if new_parties:
            message_parts.append(f"{len(new_parties)} new party/parties created")
        if existing_parties:
            message_parts.append(f"{len(existing_parties)} existing party/parties linked")

        return ReviewApprovalResponse(
            contract_id=contract.id,
            party_ids=party_ids,
            message=". ".join(message_parts)
        )

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error approving extracted data: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error creating contract and parties: {str(e)}"
        )


@router.post("/reject/{job_id}")
def reject_extracted_data(
    job_id: str,
    reason: str,
    db: Session = Depends(get_db)
):
    """
    Reject extracted data and provide a reason.

    This can be used to flag incorrect extractions for review
    or retraining of the AI model.
    """
    try:
        # In a production system, you would:
        # 1. Update the job status in the database
        # 2. Log the rejection reason for analytics
        # 3. Potentially trigger a manual review workflow

        logger.info(f"Extraction rejected for job {job_id}: {reason}")

        return {
            "message": "Extraction rejected successfully",
            "job_id": job_id,
            "reason": reason
        }

    except Exception as e:
        logger.error(f"Error rejecting extracted data: {str(e)}")
        raise HTTPException(status_code=500, detail="Error rejecting data")
