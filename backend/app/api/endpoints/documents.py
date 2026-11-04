"""Human document API; extraction is performed only by the configured workflow."""
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session
from urllib.parse import quote
from types import SimpleNamespace
import logging

from app.core.config import settings
from app.core.auth import CurrentUser, require_permission
from app.core.tenancy import bind_session_to_org, get_tenant_db
from app.models.extraction_job import ExtractionJob
from app.schemas.document import DocumentUploadResponse, DocumentExtractionStatus, ExtractionResult
from app.services.document_service import document_service
from app.services.workflow_service import create_workflow_job, expire_job, retry_job, delete_job

router = APIRouter()
logger = logging.getLogger(__name__)


def _workflow_job(db: Session, job_id: str) -> ExtractionJob:
    job = db.query(ExtractionJob).filter(
        ExtractionJob.job_id == job_id,
        ExtractionJob.selected_attempt_id.isnot(None),
        ExtractionJob.deleted_at.is_(None),
    ).first()
    if job is None:
        raise HTTPException(status_code=404, detail="Workflow job not found")
    return job


def _upload_response(job: ExtractionJob) -> DocumentUploadResponse:
    return DocumentUploadResponse(job_id=job.job_id, filename=job.filename,
                                  file_path="", message=job.message or "Queued for extraction",
                                  status=job.status)


@router.post("/upload", response_model=DocumentUploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    db: Session = Depends(get_tenant_db),
    user: CurrentUser = Depends(require_permission("document:upload")),
):
    if not settings.WORKFLOW_UPLOADS_ENABLED or not settings.WORKFLOW_CONFIGURED:
        raise HTTPException(status_code=503, detail="Workflow uploads are paused")
    file_info = await document_service.save_uploaded_file(file, org_id=user.org_id)
    committing = False
    try:
        job = create_workflow_job(db, file_info, user.org_id)
        response = _upload_response(job)
        committing = True
        db.commit()
    except Exception:
        db.rollback()
        # A lost commit response is ambiguous. Never delete a possibly committed
        # original: prove absence in a fresh scoped transaction first. If the DB
        # remains unavailable, the durable storage inventory enables reconciliation.
        safe_to_delete = not committing
        if committing:
            try:
                bind_session_to_org(db, user.org_id)
                exists = db.query(ExtractionJob.job_id).filter_by(job_id=file_info["job_id"]).first()
                safe_to_delete = exists is None
                db.rollback()
            except Exception:
                db.rollback()
        try:
            if safe_to_delete:
                document_service.delete_original(file_info["storage_key"])
        except Exception:
            logger.error("Upload orphan requires storage reconciliation")
        logger.error("Workflow upload transaction failed")
        raise HTTPException(status_code=503, detail="Document could not be queued")
    return response


@router.get("/status/{job_id}", response_model=DocumentExtractionStatus)
def get_extraction_status(
    job_id: str, db: Session = Depends(get_tenant_db),
    _user=Depends(require_permission("document:upload")),
):
    _workflow_job(db, job_id)
    job = expire_job(db, job_id)
    db.commit()
    result = ExtractionResult(**job.parsed_results) if job.status == "completed" and job.parsed_results else None
    return DocumentExtractionStatus(job_id=job.job_id, status=job.status,
                                    message=job.message, result=result, created_at=job.created_at)


@router.get("/results/{job_id}", response_model=ExtractionResult)
def get_extraction_results(
    job_id: str, db: Session = Depends(get_tenant_db),
    _user=Depends(require_permission("document:upload")),
):
    job = _workflow_job(db, job_id)
    if job.status != "completed":
        raise HTTPException(status_code=409, detail="Extraction is not completed")
    if not job.parsed_results:
        raise HTTPException(status_code=503, detail="Extraction result unavailable")
    return ExtractionResult(**job.parsed_results)


def original_response(job, content: bytes) -> Response:
    filename = quote(job.filename or "document", safe="")
    return Response(content=content, media_type=job.content_type,
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}",
                             "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


@router.get("/file/{job_id}")
def get_source_document(
    job_id: str, db: Session = Depends(get_tenant_db),
    _user=Depends(require_permission("document:upload")),
):
    job = _workflow_job(db, job_id)
    original = SimpleNamespace(**{name: getattr(job, name) for name in (
        "org_id", "storage_key", "size_bytes", "sha256", "filename", "content_type"
    )})
    db.commit()
    content = document_service.read_original(original)
    # Authorize again after storage I/O, so deletion during retrieval cannot
    # return a newly fetched original. No network call holds a DB transaction.
    _workflow_job(db, job_id)
    db.commit()
    return original_response(original, content)


@router.post("/{job_id}/retry", response_model=DocumentUploadResponse)
def retry_document(
    job_id: str, db: Session = Depends(get_tenant_db),
    _user=Depends(require_permission("document:upload")),
):
    if not settings.WORKFLOW_UPLOADS_ENABLED or not settings.WORKFLOW_CONFIGURED:
        raise HTTPException(status_code=503, detail="Workflow uploads are paused")
    _workflow_job(db, job_id)
    job = retry_job(db, job_id)
    db.commit()
    return _upload_response(job)


@router.delete("/{job_id}")
def delete_document(
    job_id: str, db: Session = Depends(get_tenant_db),
    _user=Depends(require_permission("document:upload")),
):
    _workflow_job(db, job_id)
    delete_job(db, job_id)
    db.commit()
    return {"message": "Document access revoked; storage cleanup queued", "cleanup_status": "pending"}
