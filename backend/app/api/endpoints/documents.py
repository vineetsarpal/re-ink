"""
API endpoints for document upload and extraction workflow.
"""
import uuid
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, BackgroundTasks, Body
from sqlalchemy.orm import Session
from datetime import datetime
import logging

from app.db.database import get_db
from app.schemas.document import (
    DocumentUploadResponse,
    DocumentExtractionStatus,
    ExtractionResult
)
from app.services.document_service import document_service
from app.services.landingai_service import landingai_service
from app.services.extraction_store import extraction_store

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/upload", response_model=DocumentUploadResponse)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """
    Upload a reinsurance contract document for processing.

    This endpoint:
    1. Validates the uploaded file
    2. Saves it to disk
    3. Initiates extraction job with LandingAI
    4. Returns job ID for status tracking
    """
    try:
        # Save the uploaded file
        file_info = await document_service.save_uploaded_file(file)

        # Submit to LandingAI for extraction (in background)
        background_tasks.add_task(
            process_document_extraction,
            file_info["file_path"],
            file_info["job_id"]
        )

        # Store initial job status
        extraction_store.create_job(file_info["job_id"], {
            "status": "processing",
            "filename": file_info["filename"],
            "file_path": file_info["file_path"],
            "message": "Document uploaded and extraction started",
            "created_at": datetime.utcnow()
        })

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


async def process_document_extraction(file_path: str, job_id: str):
    """
    Background task to process document extraction via LandingAI ADE Parse API.
    
    ADE Parse is synchronous and returns results immediately, but processing
    can take time, so we run it in a background task.
    """
    try:
        # Update job status to processing
        extraction_store.update_job(job_id, {
            "status": "processing",
            "message": "Processing document with LandingAI ADE Parse..."
        })

        # Parse document using LandingAI ADE Parse API
        # This is synchronous but may take time for large documents
        raw_results = await landingai_service.submit_document_for_extraction(file_path)
        
        # Parse the results to extract contract and party data
        parsed_results = landingai_service.parse_extraction_results(raw_results)
        
        # Extract job_id from metadata
        job_id_from_api = raw_results.get("metadata", {}).get("job_id")
        
        # Update job status with results
        extraction_store.update_job(job_id, {
            "status": "completed",
            "message": "Extraction completed successfully",
            "landingai_job_id": job_id_from_api,
            "raw_results": raw_results,  # Store raw results for reference
            "parsed_results": parsed_results,  # Store parsed results
            "completed_at": datetime.utcnow()
        })
        
        logger.info(f"Document extraction completed for job {job_id}")

    except Exception as e:
        logger.error(f"Error processing document extraction: {str(e)}", exc_info=True)
        extraction_store.update_job(job_id, {
            "status": "failed",
            "message": f"Extraction failed: {str(e)}",
            "error": str(e),
            "failed_at": datetime.utcnow()
        })


@router.get("/status/{job_id}", response_model=DocumentExtractionStatus)
async def get_extraction_status(job_id: str):
    """
    Get the status of a document extraction job.

    Returns:
    - Job status (processing, completed, failed)
    - Extracted data if completed
    """
    job = extraction_store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # If job is completed, use the parsed results
    result = None
    if job["status"] == "completed" and "parsed_results" in job:
        try:
            # Use the parsed results stored in the job
            parsed_results = job["parsed_results"]
            result = ExtractionResult(**parsed_results)
        except Exception as e:
            logger.error(f"Error creating ExtractionResult: {str(e)}")
            # If parsing fails, try to parse from raw results
            if "raw_results" in job:
                try:
                    parsed_results = landingai_service.parse_extraction_results(job["raw_results"])
                    result = ExtractionResult(**parsed_results)
                except Exception as parse_error:
                    logger.error(f"Error parsing raw results: {str(parse_error)}")

    # Ensure created_at is set, use current time if missing (shouldn't happen)
    created_at = job.get("created_at")
    if created_at is None:
        created_at = datetime.utcnow()
        # Update the job with created_at for future requests
        extraction_store.update_job(job_id, {"created_at": created_at})
    
    return DocumentExtractionStatus(
        job_id=job_id,
        status=job["status"],
        message=job.get("message"),
        result=result,
        created_at=created_at
    )


@router.get("/results/{job_id}", response_model=ExtractionResult)
async def get_extraction_results(job_id: str):
    """
    Get the extracted data for a completed job.

    Returns structured contract and party data ready for review.
    """
    job = extraction_store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job["status"] != "completed":
        raise HTTPException(
            status_code=400,
            detail=f"Job is not completed. Current status: {job['status']}"
        )

    try:
        # Use the parsed results stored in the job
        if "parsed_results" in job:
            parsed_results = job["parsed_results"]
            return ExtractionResult(**parsed_results)
        elif "raw_results" in job:
            # Parse from raw results if parsed results not available
            parsed_results = landingai_service.parse_extraction_results(job["raw_results"])
            return ExtractionResult(**parsed_results)
        else:
            raise HTTPException(
                status_code=500,
                detail="No results available for this job"
            )

    except Exception as e:
        logger.error(f"Error retrieving extraction results: {str(e)}")
        raise HTTPException(status_code=500, detail="Error retrieving results")


@router.delete("/{job_id}")
async def delete_document(job_id: str):
    """
    Delete a document and its associated extraction data.
    """
    job = extraction_store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Delete the file
    document_service.delete_file(job["file_path"])

    # Remove job from tracking
    extraction_store.delete_job(job_id)

    return {"message": "Document deleted successfully"}


def _build_mock_extraction_result() -> ExtractionResult:
    """Return a reusable mock extraction payload."""
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
            "coverage_description": "Coverage for property damage from natural catastrophes including hurricanes, tornadoes, and wildfires",
            "terms_and_conditions": "Standard reinsurance terms apply with quarterly reporting",
            "special_provisions": "Coverage excludes flood and earthquake unless specifically endorsed"
        },
        "parties_data": [
            {
                "name": "ABC Insurance Company",
                "party_type": "cedent",
                "email": "contact@abcinsurance.com",
                "phone": "+1-555-0100",
                "address_line1": "123 Main Street",
                "address_line2": "Suite 400",
                "city": "New York",
                "state": "NY",
                "postal_code": "10001",
                "country": "United States",
                "registration_number": "12-3456789",
                "license_number": "NY-123456"
            },
            {
                "name": "XYZ Reinsurance Ltd",
                "party_type": "reinsurer",
                "email": "info@xyzre.com",
                "phone": "+44-20-1234-5678",
                "address_line1": "456 Financial District",
                "city": "London",
                "postal_code": "EC2N 2DB",
                "country": "United Kingdom",
                "registration_number": "UK-987654321",
                "license_number": "FCA-654321"
            },
            {
                "name": "Global Reinsurance Brokers",
                "party_type": "broker",
                "email": "brokers@globalrebrokers.com",
                "phone": "+1-555-0200",
                "address_line1": "789 Broker Lane",
                "city": "Chicago",
                "state": "IL",
                "postal_code": "60601",
                "country": "United States"
            }
        ],
        "confidence_score": 0.92,
        "extraction_metadata": {
            "parse_job_id": "test-mock-job-123",
            "filename": "test_contract.pdf",
            "page_count": 15,
            "parse_duration_ms": 3500,
            "markdown_length": 25000
        }
    }

    return ExtractionResult(**mock_data)


@router.get("/test-mock-data", response_model=ExtractionResult)
async def get_mock_extraction_data():
    """
    Test endpoint that returns mock extraction data to verify frontend works correctly.
    Useful for debugging the review form UI without needing actual document extraction.
    """
    return _build_mock_extraction_result()


@router.post("/mock-job", response_model=DocumentExtractionStatus)
async def seed_mock_extraction_job(job_id: str | None = Body(default=None, embed=True)):
    """
    Seed the extraction store with a completed mock job for offline testing.

    Returns the job metadata so agents and review flows can be exercised without
    triggering LandingAI.
    """
    job_id = job_id or str(uuid.uuid4())
    mock_result = _build_mock_extraction_result()
    created_at = datetime.utcnow()

    extraction_store.create_job(
        job_id,
        {
            "status": "completed",
            "filename": mock_result.extraction_metadata.get("filename", "mock_contract.pdf")
            if mock_result.extraction_metadata
            else "mock_contract.pdf",
            "file_path": f"/mock/{job_id}.pdf",
            "message": "Mock extraction completed",
            "parsed_results": mock_result.model_dump(),
            "raw_results": mock_result.model_dump(),
            "created_at": created_at,
            "completed_at": created_at,
        },
    )

    return DocumentExtractionStatus(
        job_id=job_id,
        status="completed",
        message="Mock extraction job seeded for offline testing.",
        result=mock_result,
        created_at=created_at,
    )
