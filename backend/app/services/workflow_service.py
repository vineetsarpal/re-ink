"""PostgreSQL is the lifecycle authority. Callers commit each operation atomically."""
from datetime import timedelta
import hashlib
import json
import random
import uuid
from fastapi import HTTPException
from sqlalchemy import delete, func, select
from app.core.config import settings
from app.models.extraction_job import ExtractionJob
from app.models.workflow import ExtractionAttempt, WorkflowOutbox, WorkflowReceipt, StorageCleanup

ACTIVE = {"queued", "processing"}


def now(db):
    return db.scalar(select(func.clock_timestamp()))


def _setting(name, default):
    return getattr(settings, name, default)


def _new_attempt(db, job, number):
    timestamp = now(db)
    attempt = ExtractionAttempt(attempt_id=str(uuid.uuid4()), job_id=job.job_id, org_id=job.org_id, number=number, status="queued", created_at=timestamp, deadline_at=timestamp + timedelta(seconds=_setting("WORKFLOW_QUEUE_TIMEOUT_SECONDS", 600)))
    db.add(attempt)
    job.selected_attempt_id = attempt.attempt_id
    job.status = "queued"
    job.error = None
    job.failed_at = job.completed_at = None
    job.parsed_results = job.raw_results = None
    job.message = "Document queued for extraction"
    db.flush()
    db.add(WorkflowOutbox(attempt_id=attempt.attempt_id, org_id=job.org_id, payload={"schema_version": "1", "operation": "extract_reinsurance_contract", "job_id": job.job_id, "attempt_id": attempt.attempt_id}, next_delivery_at=timestamp, delivery_count=0))
    db.flush()
    return attempt


def create_workflow_job(db, file_info, org_id):
    job = ExtractionJob(job_id=file_info["job_id"], org_id=org_id, filename=file_info["filename"], status="queued", storage_key=file_info["storage_key"], content_type=file_info["content_type"], size_bytes=file_info["size_bytes"], sha256=file_info["sha256"])
    db.add(job)
    db.flush()
    _new_attempt(db, job, 1)
    return job


def _lock(db, job_id, attempt_id=None, allow_deleted=False):
    job = db.scalar(select(ExtractionJob).where(ExtractionJob.job_id == job_id).with_for_update().execution_options(populate_existing=True))
    if not job:
        raise HTTPException(404, "Job not found")
    if job.deleted_at and not allow_deleted:
        raise HTTPException(410, "Document deleted")
    if not job.selected_attempt_id or (attempt_id and attempt_id != job.selected_attempt_id):
        raise HTTPException(409, "Attempt is not current")
    attempt = db.scalar(select(ExtractionAttempt).where(ExtractionAttempt.attempt_id == job.selected_attempt_id).with_for_update().execution_options(populate_existing=True))
    return job, attempt


def _expire(db, job, attempt):
    timestamp = now(db)
    if attempt.status in ACTIVE and timestamp >= attempt.deadline_at:
        attempt.status = job.status = "timed_out"
        attempt.error_code = "PROCESSING_TIMEOUT" if attempt.accepted_at else "DISPATCH_TIMEOUT"
        attempt.error_message = "Extraction timed out. You may retry."
        attempt.completed_at = job.failed_at = timestamp
        job.error = attempt.error_code
        job.message = attempt.error_message
    return attempt.status == "timed_out"


def expire_job(db, job_id):
    job, attempt = _lock(db, job_id)
    _expire(db, job, attempt)
    db.flush()
    return job


def _start(db, job, attempt):
    if attempt.status == "queued":
        timestamp = now(db)
        attempt.accepted_at = timestamp
        attempt.deadline_at = timestamp + timedelta(seconds=_setting("WORKFLOW_PROCESSING_TIMEOUT_SECONDS", 600))
        attempt.status = job.status = "processing"
        job.message = "Extraction in progress"


def claim_attempt(db, job_id, attempt_id, execution_key):
    job, attempt = _lock(db, job_id, attempt_id)
    _expire(db, job, attempt)
    if attempt.status not in ACTIVE:
        db.flush()
        # Expiration must survive the rejection (endpoint commits before raising).
        return {"rejection": 409, "detail": "Attempt is no longer active"}
    decision = "already_claimed"
    if attempt.execution_key is None or attempt.execution_key == execution_key:
        attempt.execution_key = execution_key
        _start(db, job, attempt)
        decision = "run"
        outbox = db.get(WorkflowOutbox, attempt.attempt_id)
        outbox.acknowledged_at = now(db)
        outbox.lease_token = outbox.lease_until = None
    db.flush()
    response = {"schema_version": "1", "job_id": job_id, "attempt_id": attempt_id, "decision": decision}
    response["deadline_at"] = attempt.deadline_at
    return response


def ingest_event(db, event):
    payload = event.model_dump(mode="json", exclude_unset=True)
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    job, attempt = _lock(db, event.job_id, event.attempt_id)
    receipt = db.get(WorkflowReceipt, (event.attempt_id, event.event_id))
    if receipt:
        if receipt.digest != digest:
            raise HTTPException(409, "Event identity conflict")
        return receipt.acknowledgement
    _expire(db, job, attempt)
    if attempt.status not in ACTIVE:
        return {"rejection": 409, "detail": "Attempt is no longer active"}
    if event.status == "processing":
        _start(db, job, attempt)
    else:
        attempt.status = job.status = event.status
        attempt.completed_at = now(db)
        if event.status == "completed":
            job.parsed_results = event.result.to_extraction_result().model_dump(mode="json", exclude_unset=True)
            job.completed_at = attempt.completed_at
            job.message = "Extraction completed successfully"
        else:
            attempt.error_code = event.error.code
            attempt.error_message = event.error.message
            job.error = event.error.code
            job.message = event.error.message
            job.failed_at = attempt.completed_at
    outbox = db.get(WorkflowOutbox, attempt.attempt_id)
    outbox.acknowledged_at = now(db)
    outbox.lease_token = outbox.lease_until = None
    attempt.workflow_execution_id = event.workflow_execution_id
    ack = {"schema_version": "1", "event_id": event.event_id, "status": "acknowledged"}
    db.add(WorkflowReceipt(attempt_id=event.attempt_id, event_id=event.event_id, org_id=job.org_id, digest=digest, acknowledgement=ack))
    db.flush()
    return ack


def retry_job(db, job_id):
    job, attempt = _lock(db, job_id)
    _expire(db, job, attempt)
    if job.status not in {"failed", "timed_out"}:
        raise HTTPException(409, "Only failed or timed-out jobs can be retried")
    _new_attempt(db, job, attempt.number + 1)
    return job


def delete_job(db, job_id):
    job = db.scalar(select(ExtractionJob).where(ExtractionJob.job_id == job_id).with_for_update())
    if not job or job.deleted_at:
        raise HTTPException(404, "Job not found")
    timestamp = now(db)
    job.deleted_at = timestamp
    if job.storage_key or job.file_path:
        db.add(StorageCleanup(cleanup_id=str(uuid.uuid4()), org_id=job.org_id, storage_key=job.storage_key or job.file_path, job_id=job.job_id, next_attempt_at=timestamp, attempts=0))
    job.raw_results = job.parsed_results = None
    job.filename = job.file_path = job.storage_key = job.sha256 = None
    job.error = job.message = None
    job.content_type = job.size_bytes = None
    attempt_ids = select(ExtractionAttempt.attempt_id).where(ExtractionAttempt.job_id == job_id)
    db.execute(delete(WorkflowReceipt).where(WorkflowReceipt.attempt_id.in_(attempt_ids)))
    db.execute(delete(WorkflowOutbox).where(WorkflowOutbox.attempt_id.in_(attempt_ids)))
    db.execute(delete(ExtractionAttempt).where(ExtractionAttempt.job_id == job_id))
    job.selected_attempt_id = None

    db.flush()
    return job


def lease_dispatch(db):
    timestamp = now(db)
    row = db.scalar(select(WorkflowOutbox).join(ExtractionAttempt).join(ExtractionJob).where(WorkflowOutbox.acknowledged_at.is_(None), WorkflowOutbox.next_delivery_at <= timestamp, (WorkflowOutbox.lease_until.is_(None) | (WorkflowOutbox.lease_until <= timestamp)), ExtractionAttempt.status.in_(ACTIVE), ExtractionAttempt.deadline_at > timestamp, ExtractionJob.deleted_at.is_(None), ExtractionJob.selected_attempt_id == WorkflowOutbox.attempt_id).order_by(WorkflowOutbox.next_delivery_at).with_for_update(skip_locked=True, of=WorkflowOutbox).limit(1))
    if not row:
        return None
    row.lease_token = str(uuid.uuid4())
    row.lease_until = timestamp + timedelta(seconds=_setting("WORKFLOW_LEASE_SECONDS", 60))
    row.delivery_count += 1
    db.flush()
    return {"attempt_id": row.attempt_id, "token": row.lease_token, "payload": row.payload, "count": row.delivery_count}


def finish_dispatch(db, lease, accepted=False, permanent=False, retry_after=None):
    # Always lock job before attempt/outbox to share the callback/deletion fence.
    job, attempt = _lock(db, lease["payload"]["job_id"], lease["attempt_id"], allow_deleted=True)
    row = db.scalar(select(WorkflowOutbox).where(WorkflowOutbox.attempt_id == lease["attempt_id"]).with_for_update().execution_options(populate_existing=True))
    if row.lease_token != lease["token"] or row.lease_until is None or row.lease_until <= now(db):
        return False
    timestamp = now(db)
    _expire(db, job, attempt)
    if job.deleted_at or attempt.status not in ACTIVE:
        row.acknowledged_at = timestamp
    elif accepted:
        _start(db, job, attempt)
        row.acknowledged_at = timestamp
    elif permanent:
        attempt.status = job.status = "failed"
        attempt.error_code = job.error = "DISPATCH_REJECTED"
        attempt.error_message = job.message = "Workflow dispatch configuration was rejected."
        attempt.completed_at = job.failed_at = timestamp
        row.acknowledged_at = timestamp
    else:
        delay = min(60, 5 * 2 ** min(lease["count"] - 1, 4))
        if retry_after is not None:
            delay = min(60, max(0, retry_after))
        row.next_delivery_at = min(attempt.deadline_at, timestamp + timedelta(seconds=delay + random.uniform(0, 1)))
        row.last_error = "DELIVERY_RETRY"
    row.lease_token = row.lease_until = None
    db.flush()
    return True


def sweep_expired(db):
    ids = list(db.scalars(select(ExtractionJob.job_id).join(ExtractionAttempt, ExtractionJob.selected_attempt_id == ExtractionAttempt.attempt_id).where(ExtractionJob.deleted_at.is_(None), ExtractionAttempt.status.in_(ACTIVE), ExtractionAttempt.deadline_at <= func.clock_timestamp())))
    for job_id in sorted(ids):
        try:
            expire_job(db, job_id)
        except HTTPException as exc:
            # Deletion may win after the candidate snapshot.
            if exc.status_code not in (404, 409, 410):
                raise
    return len(ids)


def lease_cleanup(db):
    timestamp = now(db)
    row = db.scalar(select(StorageCleanup).where(StorageCleanup.completed_at.is_(None), StorageCleanup.next_attempt_at <= timestamp, (StorageCleanup.lease_until.is_(None) | (StorageCleanup.lease_until <= timestamp))).with_for_update(skip_locked=True).limit(1))
    if not row:
        return None
    row.attempts += 1
    row.lease_token = str(uuid.uuid4())
    row.lease_until = timestamp + timedelta(seconds=_setting("WORKFLOW_LEASE_SECONDS", 60))
    db.flush()
    return {"cleanup_id": row.cleanup_id, "storage_key": row.storage_key, "token": row.lease_token}


def finish_cleanup(db, lease, succeeded):
    row = db.scalar(select(StorageCleanup).where(StorageCleanup.cleanup_id == lease["cleanup_id"]).with_for_update().execution_options(populate_existing=True))
    if not row or row.lease_token != lease["token"] or row.lease_until <= now(db):
        return False
    if succeeded:
        if row.job_id:
            db.execute(delete(ExtractionJob).where(ExtractionJob.job_id == row.job_id, ExtractionJob.deleted_at.is_not(None)))
        db.delete(row)
    else:
        row.next_attempt_at = now(db) + timedelta(seconds=min(300, 5 * 2 ** min(row.attempts, 6)))
        row.lease_token = row.lease_until = None
    db.flush()
    return True
