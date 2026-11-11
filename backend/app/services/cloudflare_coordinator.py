"""Unwired backend foundation for a fenced Cloudflare extraction consumer.

Every caller must have a session already scoped to a trusted, authenticated
tenant; neither queue message fields nor user-provided org identifiers establish
that scope. Commit each operation before responding or making a provider call.
No public API is exposed until an authenticated transport is implemented.
"""
import hashlib
import secrets

from fastapi import HTTPException

from app.models.cloudflare_execution import CloudflareExecution
from app.models.extraction_quota import QuotaReservation
from app.core.config import settings
from app.services.extraction_quota import start_provider_call
from app.schemas.workflow import parse_workflow_event
from app.services.workflow_service import ACTIVE, _expire, _lock, _start


def claim_preparation(db, job_id: str, attempt_id: str) -> dict:
    """Atomically grant the single preparation claim for an attempt."""
    job, attempt = _lock(db, job_id, attempt_id, machine=True)
    _expire(db, job, attempt)
    execution = db.get(CloudflareExecution, attempt_id)
    if attempt.status not in ACTIVE:
        return {"decision": "closed"}
    if execution:
        if execution.terminal_event is not None:
            return {"decision": "terminal", "event": execution.terminal_event}
        return {"decision": "in_progress"}
    if attempt.execution_key is not None:
        return {"decision": "closed"}
    reservation = db.get(QuotaReservation, (job.org_id, attempt_id))
    if reservation is None:
        raise HTTPException(409, "Extraction reservation unavailable")
    token = secrets.token_urlsafe(32)
    digest = hashlib.sha256(token.encode()).hexdigest()
    db.add(CloudflareExecution(attempt_id=attempt_id, org_id=job.org_id,
                               token_digest=digest))
    attempt.execution_key = digest
    _start(db, job, attempt)
    db.flush()
    return {"decision": "start", "checkpoint_token": token}


def checkpoint_terminal_event(db, job_id: str, attempt_id: str, token: str, body: bytes) -> bool:
    """Persist a validated terminal result for replay, requiring the one-shot grant."""
    event = parse_workflow_event(body)
    if (event.job_id != job_id or event.attempt_id != attempt_id or
            event.event_id != "terminal" or event.status not in {"completed", "failed"}):
        raise HTTPException(422, "Invalid terminal event")
    job, attempt = _lock(db, job_id, attempt_id, machine=True)
    _expire(db, job, attempt)
    if attempt.status not in ACTIVE:
        return None
    execution = db.get(CloudflareExecution, attempt_id)
    supplied_digest = hashlib.sha256(token.encode()).hexdigest()
    if not execution or not secrets.compare_digest(execution.token_digest, supplied_digest):
        raise HTTPException(403, "Invalid checkpoint credential")
    if event.status == "completed":
        reservation = db.get(QuotaReservation, (job.org_id, attempt_id))
        if reservation is None or not reservation.provider_started:
            raise HTTPException(409, "Completion requires a counted provider start")
    payload = event.model_dump(mode="json", exclude_unset=True)
    if execution.terminal_event is not None and execution.terminal_event != payload:
        raise HTTPException(409, "Terminal checkpoint conflict")
    execution.terminal_event = payload
    db.flush()
    return True


def authorize_provider_access(db, job_id: str, attempt_id: str, token: str) -> str | None:
    """Verify the claim owner before accessing its credential or document."""
    job, attempt = _lock(db, job_id, attempt_id, machine=True)
    _expire(db, job, attempt)
    if attempt.status not in ACTIVE:
        return None
    execution = db.get(CloudflareExecution, attempt_id)
    supplied = hashlib.sha256(token.encode()).hexdigest()
    if (not execution or execution.terminal_event is not None or
            not secrets.compare_digest(execution.token_digest, supplied) or
            not attempt.execution_key or not secrets.compare_digest(attempt.execution_key, supplied)):
        raise HTTPException(403, "Invalid checkpoint credential")
    return supplied


def authorize_provider_start(db, job_id: str, attempt_id: str, token: str) -> bool:
    if authorize_provider_access(db, job_id, attempt_id, token) is None:
        return False
    job, _ = _lock(db, job_id, attempt_id, machine=True)
    reservation = db.get(QuotaReservation, (job.org_id, attempt_id))
    if reservation is None or reservation.provider_started:
        raise HTTPException(409, "Provider authorization unavailable")
    start_provider_call(db, job.org_id, attempt_id,
                        global_trial_call_limit=settings.EXTRACTION_GLOBAL_TRIAL_CALL_MONTHLY_LIMIT)
    return True
