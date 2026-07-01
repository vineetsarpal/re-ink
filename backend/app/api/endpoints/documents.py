"""
API endpoints for document upload and extraction workflow.
"""
from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime, timezone
import logging

from app.core.config import settings
from app.db.database import SessionLocal
from app.core.auth import CurrentUser, get_current_user
from app.core.tenancy import bind_session_to_org, get_tenant_db
from app.schemas.document import (
    DocumentUploadResponse,
    DocumentExtractionStatus,
    ReviewData,
    ReviewApprovalResponse,
    ExtractionResult
)
from app.services.document_service import document_service
from app.services.landingai_service import landingai_service
from app.models.extraction_job import ExtractionJob

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/upload", response_model=DocumentUploadResponse)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    api_key: Optional[str] = Form(None),
    db: Session = Depends(get_tenant_db),
    user: CurrentUser = Depends(get_current_user),
):
    """
    Upload a reinsurance contract document for processing.

    This endpoint:
    1. Validates the uploaded file
    2. Saves it to disk
    3. Initiates extraction job with LandingAI (using provided or server API key)
    4. Returns job ID for status tracking
    """
    resolved_key = api_key or settings.LANDINGAI_API_KEY
    if not resolved_key:
        raise HTTPException(
            status_code=400,
            detail="A LandingAI API key is required. Please enter your key in the upload form."
        )

    try:
        file_info = await document_service.save_uploaded_file(file, org_id=user.org_id)

        job = ExtractionJob(
            job_id=file_info["job_id"],
            status="processing",
            filename=file_info["filename"],
            file_path=file_info["file_path"],
            message="Document uploaded and extraction started",
        )
        db.add(job)
        db.commit()

        background_tasks.add_task(
            process_document_extraction,
            file_info["file_path"],
            file_info["job_id"],
            resolved_key,
            user.org_id,
        )

        return DocumentUploadResponse(
            job_id=file_info["job_id"],
            filename=file_info["filename"],
            file_path=file_info["file_path"],
            message="Document uploaded successfully. Extraction in progress.",
            status="processing"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error uploading document: {str(e)}")
        raise HTTPException(status_code=500, detail="Error uploading document")


async def process_document_extraction(
    file_path: str, job_id: str, api_key: str, org_id: str
):
    """
    Background task to process document extraction via LandingAI ADE Parse API.
    Uses a fresh DB session since background tasks run outside the request
    lifecycle; it must be bound to the job's org so RLS lets it read and update
    the job it owns.
    """
    db = SessionLocal()
    bind_session_to_org(db, org_id)
    try:
        raw_results = await landingai_service.submit_document_for_extraction(
            file_path, api_key=api_key
        )
        parsed_results = landingai_service.parse_extraction_results(raw_results)
        job_id_from_api = raw_results.get("metadata", {}).get("job_id")

        job = db.query(ExtractionJob).filter(ExtractionJob.job_id == job_id).first()
        if job:
            job.status = "completed"
            job.message = "Extraction completed successfully"
            job.landingai_job_id = job_id_from_api
            job.raw_results = raw_results
            job.parsed_results = parsed_results
            job.completed_at = datetime.now(timezone.utc)
            db.commit()

        logger.info(f"Document extraction completed for job {job_id}")

    except Exception as e:
        logger.error(f"Error processing document extraction: {str(e)}", exc_info=True)
        job = db.query(ExtractionJob).filter(ExtractionJob.job_id == job_id).first()
        if job:
            job.status = "failed"
            job.message = f"Extraction failed: {str(e)}"
            job.error = str(e)
            job.failed_at = datetime.now(timezone.utc)
            db.commit()
    finally:
        db.close()


@router.get("/status/{job_id}", response_model=DocumentExtractionStatus)
async def get_extraction_status(job_id: str, db: Session = Depends(get_tenant_db)):
    """
    Get the status of a document extraction job.

    Returns:
    - Job status (processing, completed, failed)
    - Extracted data if completed
    """
    job = db.query(ExtractionJob).filter(ExtractionJob.job_id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    result = None
    if job.status == "completed" and job.parsed_results:
        try:
            result = ExtractionResult(**job.parsed_results)
        except Exception as e:
            logger.error(f"Error creating ExtractionResult: {str(e)}")
            if job.raw_results:
                try:
                    parsed = landingai_service.parse_extraction_results(job.raw_results)
                    result = ExtractionResult(**parsed)
                except Exception as parse_error:
                    logger.error(f"Error parsing raw results: {str(parse_error)}")

    return DocumentExtractionStatus(
        job_id=job.job_id,
        status=job.status,
        message=job.message,
        result=result,
        created_at=job.created_at,
    )


@router.get("/results/{job_id}", response_model=ExtractionResult)
async def get_extraction_results(job_id: str, db: Session = Depends(get_tenant_db)):
    """
    Get the extracted data for a completed job.
    """
    job = db.query(ExtractionJob).filter(ExtractionJob.job_id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status != "completed":
        raise HTTPException(
            status_code=400,
            detail=f"Job is not completed. Current status: {job.status}"
        )

    try:
        if job.parsed_results:
            return ExtractionResult(**job.parsed_results)
        elif job.raw_results:
            parsed = landingai_service.parse_extraction_results(job.raw_results)
            return ExtractionResult(**parsed)
        else:
            raise HTTPException(status_code=500, detail="No results available for this job")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving extraction results: {str(e)}")
        raise HTTPException(status_code=500, detail="Error retrieving results")


@router.get("/file/{job_id}")
async def get_source_document(job_id: str, db: Session = Depends(get_tenant_db)):
    """
    Stream the original uploaded document for a job, for the review preview
    panel. Returns 404 when the file is unavailable (e.g. mock jobs, which
    carry no file on disk) so the frontend can degrade gracefully.
    """
    from fastapi.responses import FileResponse
    from pathlib import Path

    job = db.query(ExtractionJob).filter(ExtractionJob.job_id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if not job.file_path or not Path(job.file_path).exists():
        raise HTTPException(status_code=404, detail="Source document not available for this job")

    suffix = Path(job.file_path).suffix.lower()
    media_type = {
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".doc": "application/msword",
    }.get(suffix, "application/octet-stream")

    return FileResponse(
        job.file_path,
        media_type=media_type,
        filename=job.filename or Path(job.file_path).name,
        content_disposition_type="inline",
    )


@router.delete("/{job_id}")
async def delete_document(job_id: str, db: Session = Depends(get_tenant_db)):
    """
    Delete a document and its associated extraction data.
    """
    job = db.query(ExtractionJob).filter(ExtractionJob.job_id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    document_service.delete_file(job.file_path)
    db.delete(job)
    db.commit()

    return {"message": "Document deleted successfully"}


@router.post("/mock-job", response_model=DocumentExtractionStatus)
async def seed_mock_job(
    payload: Optional[dict] = None,
    db: Session = Depends(get_tenant_db)
):
    """
    Seed a mock extraction job for testing (skips LandingAI).

    Rotates through several realistic scenarios based on sample
    reinsurance documents. Each call generates a unique contract number
    so the flow can be repeated without duplicate-contract errors.
    """
    import uuid
    import random

    job_id = (payload or {}).get("job_id") or str(uuid.uuid4())
    suffix = job_id[:6].upper()

    existing = db.query(ExtractionJob).filter(ExtractionJob.job_id == job_id).first()
    if existing:
        db.delete(existing)
        db.commit()

    def src(page: int, text: str, value=None) -> dict:
        """Build a mock FieldSource so the source-evidence UI is demonstrable.

        The bounding box is staggered vertically by a stable hash of the text so
        several fields on the same page don't render stacked on top of each
        other in the document preview — purely cosmetic for the offline demo.
        """
        top = round(0.08 + (sum(ord(c) for c in text) % 70) / 100.0, 3)  # 0.08..0.77
        return {
            "value": value,
            "source_text": text,
            "page_number": page,
            "chunk_id": f"mock-{uuid.uuid4().hex[:8]}",
            "bbox": {"left": 0.08, "top": top, "right": 0.92, "bottom": round(top + 0.05, 3)},
            "confidence": None,
        }

    scenarios = [
        {
            "contract_data": {
                "contract_number": f"QS-2024-{suffix}",
                "contract_name": "100% Quota Share Reinsurance Contract",
                "contract_type": "quota share",
                "contract_sub_type": "quota_share",
                "contract_nature": "proportional",
                "effective_date": "2024-07-01",
                "expiration_date": "2025-06-30",
                "premium_description": "100% of gross written premium",
                "currency": "USD",
                "limit_description": "100% quota share",
                "line_of_business": "property",
                "coverage_territory": "United States",
                "coverage_description": "All property risks per original policy terms",
            },
            "parties_data": [
                {"name": "Vesta Fire Insurance Corp", "role": "cedant", "is_active": True},
                {"name": "Affirmative Insurance Company", "role": "reinsurer", "is_active": True},
            ],
            "field_sources": {
                "contract": {
                    "contract_name": src(1, "100% QUOTA SHARE REINSURANCE CONTRACT between Vesta Fire Insurance Corp and Affirmative Insurance Company"),
                    "effective_date": src(1, "This Contract shall apply to losses occurring during the period from July 1, 2024 to June 30, 2025."),
                    "expiration_date": src(1, "This Contract shall apply to losses occurring during the period from July 1, 2024 to June 30, 2025."),
                    "premium_description": src(2, "The Reinsurer shall receive 100% of the gross written premium of the Company."),
                    "line_of_business": src(2, "This Contract covers all Property business written by the Company."),
                    "coverage_territory": src(2, "The territorial scope of this Contract is the United States of America."),
                    # coverage_description intentionally ungrounded -> "No source found"
                },
                "parties": [
                    {"name": src(1, "between Vesta Fire Insurance Corp (hereinafter the 'Company')")},
                    {"name": src(1, "and Affirmative Insurance Company (hereinafter the 'Reinsurer')")},
                ],
            },
            "confidence_score": 0.91,
            "extraction_metadata": {"filename": "quota-share-reinsurance-contract.pdf", "page_count": 4},
        },
        {
            "contract_data": {
                "contract_number": f"XOL-2024-{suffix}",
                "contract_name": "Excess of Loss Reinsurance Agreement",
                "contract_type": "excess of loss",
                "contract_sub_type": "per_occurrence",
                "contract_nature": "non-proportional",
                "effective_date": "2024-01-01",
                "expiration_date": "2024-12-31",
                "premium_description": "Rate on line 8.5%",
                "premium_amount": "850000.00",
                "currency": "USD",
                "limit_description": "$10,000,000 excess of $5,000,000",
                "limit_amount": "10000000.00",
                "retention_description": "$5,000,000 each and every loss occurrence",
                "retention_amount": "5000000.00",
                "line_of_business": "casualty",
                "coverage_territory": "Worldwide",
                "coverage_description": "Excess of loss coverage for catastrophe events",
            },
            "parties_data": [
                {"name": "Republic Insurance Company", "role": "cedant", "is_active": True},
                {"name": "Winterthur Swiss Insurance", "role": "reinsurer", "is_active": True},
            ],
            "field_sources": {
                "contract": {
                    "contract_name": src(1, "EXCESS OF LOSS REINSURANCE AGREEMENT"),
                    "limit_description": src(3, "The Reinsurer shall be liable for $10,000,000 excess of $5,000,000 each and every loss occurrence."),
                    "limit_amount": src(3, "The Reinsurer shall be liable for $10,000,000 excess of $5,000,000 each and every loss occurrence.", value=10000000.0),
                    "retention_description": src(3, "The Company shall retain $5,000,000 each and every loss occurrence."),
                    "premium_description": src(4, "Rate on line of 8.5% applied to the subject premium income."),
                },
                "parties": [
                    {"name": src(1, "Republic Insurance Company, the Reinsured")},
                    {},  # reinsurer name ungrounded -> "Needs manual verification"
                ],
            },
            "confidence_score": 0.88,
            "extraction_metadata": {"filename": "excess-of-loss-reinsurance-agreement.pdf", "page_count": 6},
        },
        {
            "contract_data": {
                "contract_number": f"SP-2025-{suffix}",
                "contract_name": "First Surplus Treaty Reinsurance Contract",
                "contract_type": "surplus",
                "contract_sub_type": "first_surplus",
                "contract_nature": "proportional",
                "effective_date": "2025-01-01",
                "expiration_date": "2025-12-31",
                "premium_description": "Pro-rata share of original premium",
                "currency": "USD",
                "limit_description": "4 lines surplus, maximum $20,000,000",
                "limit_amount": "20000000.00",
                "retention_description": "$5,000,000 net retention per risk",
                "retention_amount": "5000000.00",
                "commission_description": "30% ceding commission",
                "commission_rate": "30.00",
                "line_of_business": "property",
                "coverage_territory": "United States and Canada",
                "coverage_description": "Commercial property and inland marine risks",
            },
            "parties_data": [
                {"name": "National Union Fire Insurance", "role": "cedant", "is_active": True},
                {"name": "Swiss Reinsurance Company Ltd", "role": "reinsurer", "is_active": True},
                {"name": "Aon Benfield Securities", "role": "broker", "is_active": True},
            ],
            "field_sources": {
                "contract": {
                    "contract_name": src(1, "FIRST SURPLUS TREATY REINSURANCE CONTRACT"),
                    "effective_date": src(1, "Period: January 1, 2025 to December 31, 2025, both days inclusive."),
                    "expiration_date": src(1, "Period: January 1, 2025 to December 31, 2025, both days inclusive."),
                    "limit_description": src(2, "Maximum cession of 4 lines, subject to a maximum of $20,000,000 any one risk."),
                    "limit_amount": src(2, "Maximum cession of 4 lines, subject to a maximum of $20,000,000 any one risk.", value=20000000.0),
                    "retention_description": src(2, "The Company shall retain net for its own account $5,000,000 each and every risk."),
                    "commission_description": src(4, "The Reinsurer shall allow the Company a ceding commission of 30% on ceded premiums."),
                    "commission_rate": src(4, "The Reinsurer shall allow the Company a ceding commission of 30% on ceded premiums.", value=30.0),
                },
                "parties": [
                    {"name": src(1, "National Union Fire Insurance (the 'Company')")},
                    {"name": src(1, "Swiss Reinsurance Company Ltd (the 'Reinsurer')")},
                    {},  # broker ungrounded
                ],
            },
            "confidence_score": 0.94,
            "extraction_metadata": {"filename": "first-surplus-treaty.pdf", "page_count": 8},
        },
    ]

    mock_parsed = random.choice(scenarios)

    job = ExtractionJob(
        job_id=job_id,
        status="completed",
        filename=mock_parsed["extraction_metadata"]["filename"],
        file_path="",
        message="Mock extraction completed",
        parsed_results=mock_parsed,
        completed_at=datetime.now(timezone.utc),
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    return DocumentExtractionStatus(
        job_id=job.job_id,
        status=job.status,
        message=job.message,
        result=ExtractionResult(**mock_parsed),
        created_at=job.created_at,
    )


@router.get("/test-mock-data", response_model=ExtractionResult)
async def get_mock_extraction_data():
    """
    Test endpoint that returns mock extraction data to verify frontend works correctly.
    """
    mock_data = {
        "contract_data": {
            "contract_number": "RC-2024-TEST-001",
            "contract_name": "Test Property Catastrophe Reinsurance Treaty",
            "contract_type": "quota share",
            "effective_date": "2024-01-01",
            "expiration_date": "2024-12-31",
            "inception_date": "2024-01-01",
            "premium_amount": "1000000.00",
            "currency": "USD",
            "limit_amount": "5000000.00",
            "retention_amount": "500000.00",
            "commission_rate": "25.00",
            "line_of_business": "property",
            "coverage_territory": "United States",
            "coverage_description": "Coverage for property damage from natural catastrophes",
            "terms_and_conditions": "Standard reinsurance terms apply with quarterly reporting",
            "special_provisions": "Coverage excludes flood and earthquake unless specifically endorsed"
        },
        "parties_data": [
            {
                "name": "ABC Insurance Company",
                "role": "cedant",
                "email": "contact@abcinsurance.com",
                "phone": "+1-555-0100",
                "address_line1": "123 Main Street",
                "city": "New York",
                "state": "NY",
                "postal_code": "10001",
                "country": "United States",
            },
            {
                "name": "XYZ Reinsurance Ltd",
                "role": "reinsurer",
                "email": "info@xyzre.com",
                "address_line1": "456 Financial District",
                "city": "London",
                "country": "United Kingdom",
            },
        ],
        "confidence_score": 0.92,
        "extraction_metadata": {
            "parse_job_id": "test-mock-job-123",
            "filename": "test_contract.pdf",
            "page_count": 15,
        }
    }
    return ExtractionResult(**mock_data)
