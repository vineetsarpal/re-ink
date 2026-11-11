"""Expire one cross-tenant extraction through restricted discovery."""
from fastapi import HTTPException
from sqlalchemy import text

from app.core.tenancy import bind_session_to_org
from app.services.workflow_service import expire_job


def expire_next(db) -> bool:
    candidate = db.execute(text("SELECT org_id, job_id FROM public.reink_next_expired_extraction()")).first()
    if candidate is None:
        return False
    bind_session_to_org(db, candidate.org_id)
    try:
        expire_job(db, candidate.job_id, minimal=True)
    except HTTPException as exc:
        if exc.status_code not in (404, 409, 410):
            raise
    return True
