"""Create and atomically fence upload leases; callers control transactions."""
from datetime import timedelta
from fastapi import HTTPException
from sqlalchemy import func, select, update
from app.models.upload_intent import UploadIntent


def begin_upload(db, org_id, job_id, key):
    timestamp = db.scalar(select(func.clock_timestamp()))
    db.add(UploadIntent(org_id=org_id, job_id=job_id, storage_key=key,
                        status="uploading", lease_deadline=timestamp + timedelta(minutes=15)))
    db.flush()


def complete_upload(db, org_id, job_id, key):
    result = db.execute(update(UploadIntent).where(
        UploadIntent.org_id == org_id, UploadIntent.job_id == job_id,
        UploadIntent.storage_key == key, UploadIntent.status == "uploading",
        UploadIntent.lease_deadline > func.clock_timestamp(),
    ).values(status="completed").returning(UploadIntent.job_id)).scalar_one_or_none()
    if result is None:
        raise HTTPException(409, "Upload expired; please upload the document again")


def abandon_expired_upload(db, org_id, job_id):
    """Fence a stale upload before any future orphan cleanup; never deletes objects."""
    return db.execute(update(UploadIntent).where(
        UploadIntent.org_id == org_id, UploadIntent.job_id == job_id,
        UploadIntent.status == "uploading", UploadIntent.lease_deadline <= func.clock_timestamp(),
    ).values(status="abandoned").returning(UploadIntent.job_id)).scalar_one_or_none() is not None
