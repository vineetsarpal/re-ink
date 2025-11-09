"""
API endpoints for document upload and extraction workflow.
"""
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from typing import Dict, Any
import logging

from app.db.database import get_db
from app.schemas.document import (
    DocumentUploadResponse,
    DocumentExtractionStatus,
    ReviewData,
    ReviewApprovalResponse,
    ExtractionResult
)
from app.services.document_service import document_service
from app.services.landingai_service import landingai_service

router = APIRouter()
logger = logging.getLogger(__name__)

# In-memory storage for extraction jobs (in production, use Redis or database)
extraction_jobs: Dict[str, Dict[str, Any]] = {}


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
        extraction_jobs[file_info["job_id"]] = {
            "status": "processing",
            "filename": file_info["filename"],
            "file_path": file_info["file_path"],
            "message": "Document uploaded and extraction started"
        }

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
    Background task to process document extraction via LandingAI.
    """
    try:
        # Submit to LandingAI
        result = await landingai_service.submit_document_for_extraction(file_path)

        # Update job status
        extraction_jobs[job_id].update({
            "landingai_job_id": result.get("job_id"),
            "status": "submitted_to_ai",
            "message": "Document submitted to AI extraction service"
        })

        # Poll for results (in production, use webhooks)
        # For now, we'll mark as complete and store mock results
        extraction_jobs[job_id].update({
            "status": "completed",
            "message": "Extraction completed successfully"
        })

    except Exception as e:
        logger.error(f"Error processing document extraction: {str(e)}")
        extraction_jobs[job_id].update({
            "status": "failed",
            "message": f"Extraction failed: {str(e)}"
        })


@router.get("/status/{job_id}", response_model=DocumentExtractionStatus)
async def get_extraction_status(job_id: str):
    """
    Get the status of a document extraction job.

    Returns:
    - Job status (processing, completed, failed)
    - Extracted data if completed
    """
    if job_id not in extraction_jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    job = extraction_jobs[job_id]

    # If job is completed, fetch the actual results
    result = None
    if job["status"] == "completed" and "landingai_job_id" in job:
        try:
            # Fetch results from LandingAI
            raw_results = await landingai_service.get_extraction_results(
                job["landingai_job_id"]
            )
            parsed_results = landingai_service.parse_extraction_results(raw_results)

            result = ExtractionResult(**parsed_results)

        except Exception as e:
            logger.error(f"Error fetching extraction results: {str(e)}")

    return DocumentExtractionStatus(
        job_id=job_id,
        status=job["status"],
        message=job.get("message"),
        result=result,
        created_at=job.get("created_at")
    )


@router.get("/results/{job_id}", response_model=ExtractionResult)
async def get_extraction_results(job_id: str):
    """
    Get the extracted data for a completed job.

    Returns structured contract and party data ready for review.
    """
    if job_id not in extraction_jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    job = extraction_jobs[job_id]

    if job["status"] != "completed":
        raise HTTPException(
            status_code=400,
            detail=f"Job is not completed. Current status: {job['status']}"
        )

    try:
        # Fetch and parse results
        raw_results = await landingai_service.get_extraction_results(
            job.get("landingai_job_id")
        )
        parsed_results = landingai_service.parse_extraction_results(raw_results)

        return ExtractionResult(**parsed_results)

    except Exception as e:
        logger.error(f"Error retrieving extraction results: {str(e)}")
        raise HTTPException(status_code=500, detail="Error retrieving results")


@router.delete("/{job_id}")
async def delete_document(job_id: str):
    """
    Delete a document and its associated extraction data.
    """
    if job_id not in extraction_jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    job = extraction_jobs[job_id]

    # Delete the file
    document_service.delete_file(job["file_path"])

    # Remove job from tracking
    del extraction_jobs[job_id]

    return {"message": "Document deleted successfully"}
