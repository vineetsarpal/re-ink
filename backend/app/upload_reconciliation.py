"""Retained upload tombstones repeatedly remove possible late storage writes."""
from uuid import uuid4

from sqlalchemy import text

from app.services.storage_service import tenant_prefix


def upload_first(factory):
    # A durable alternating turn prevents either cleanup class from starving.
    with factory.begin() as db:
        return db.scalar(text('SELECT public.reink_cleanup_upload_first()'))


def reconcile_upload_next(factory, storage):
    token = str(uuid4())
    with factory.begin() as db:
        row = db.execute(text('SELECT * FROM public.reink_lease_expired_upload(:token)'), {'token': token}).mappings().first()
    if row is None:
        return False
    job_id, org_id, key = row['job_id'], row['org_id'], row['storage_key']
    try:
        if not key.startswith(tenant_prefix(org_id)):
            raise ValueError('Upload object does not belong to organization')
        with factory.begin() as db:
            if not db.scalar(text('SELECT public.reink_expired_upload_is_safe(:job, :token)'), {'job': job_id, 'token': token}):
                raise ValueError('Upload object is referenced or lease expired')
            storage.delete(key)
            db.scalar(text('SELECT public.reink_finish_expired_upload(:job, :token, true)'), {'job': job_id, 'token': token})
    except Exception:
        with factory.begin() as db:
            db.scalar(text('SELECT public.reink_finish_expired_upload(:job, :token, false)'), {'job': job_id, 'token': token})
    return True
