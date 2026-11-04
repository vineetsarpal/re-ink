"""Authenticated, tenant-bound n8n document/claim/event surface."""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import ValidationError
from sqlalchemy.orm import Session
from app.core.service_auth import get_workflow_db
from app.schemas.workflow import (MAX_CALLBACK_BYTES, WorkflowClaimRequest, WorkflowClaimResponse, WorkflowPayloadError, parse_workflow_event, parse_workflow_json)
from app.services.workflow_service import _lock, _expire, ACTIVE, claim_attempt, ingest_event

router = APIRouter(prefix="/workflows/extraction", tags=["workflows"])


async def bounded_body(request):
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_CALLBACK_BYTES:
            raise HTTPException(413, "Request exceeds 5 MiB")
    return bytes(body)


def committed_response(db, response):
    db.commit()
    if "rejection" in response:
        raise HTTPException(response["rejection"], response["detail"])
    return response


@router.post("/jobs/{job_id}/attempts/{attempt_id}/claim", response_model=WorkflowClaimResponse)
async def claim(job_id: str, attempt_id: str, request: Request, db: Session = Depends(get_workflow_db)):
    try:
        payload = WorkflowClaimRequest.model_validate(parse_workflow_json(await bounded_body(request), request.headers.get("content-encoding")))
    except WorkflowPayloadError as exc:
        raise HTTPException(exc.status_code, exc.detail)
    except ValidationError:
        raise HTTPException(422, "Invalid claim request")
    return committed_response(db, claim_attempt(db, job_id, attempt_id, payload.execution_key))


@router.post("/events")
async def events(request: Request, db: Session = Depends(get_workflow_db)):
    try:
        event = parse_workflow_event(await bounded_body(request), request.headers.get("content-encoding"))
    except WorkflowPayloadError as exc:
        raise HTTPException(exc.status_code, exc.detail)
    return committed_response(db, ingest_event(db, event))


@router.get("/jobs/{job_id}/document")
def document(job_id: str, attempt_id: str, db: Session = Depends(get_workflow_db)):
    from app.services.document_service import document_service
    job, attempt = _lock(db, job_id, attempt_id)
    _expire(db, job, attempt)
    if attempt.status not in ACTIVE:
        db.commit()
        raise HTTPException(409, "Attempt is no longer active")
    if not attempt.execution_key:
        raise HTTPException(409, "Attempt must be claimed before document access")
    content_type = job.content_type
    filename = job.filename or "document"
    # Snapshot metadata; release the database transaction before object storage I/O.
    from types import SimpleNamespace
    snapshot = SimpleNamespace(org_id=job.org_id, storage_key=job.storage_key, size_bytes=job.size_bytes, sha256=job.sha256, content_type=job.content_type)
    db.commit()
    data = document_service.read_original(snapshot)
    job, attempt = _lock(db, job_id, attempt_id)
    _expire(db, job, attempt)
    if attempt.status not in ACTIVE:
        db.commit()
        raise HTTPException(409, "Attempt is no longer active")
    db.commit()
    from urllib.parse import quote
    return Response(data, media_type=content_type, headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename, safe='')}", "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})
