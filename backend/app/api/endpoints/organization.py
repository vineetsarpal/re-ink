from datetime import datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.auth import CurrentUser, get_current_user, require_permission
from app.core.config import settings
from app.core.tenancy import get_tenant_db
from app.models.organization_lifecycle import OrganizationLifecycle
from app.services.trial_eligibility import trial_user_hash
from app.services.workflow_service import now, cancel_organization_extractions

router = APIRouter()


class LifecycleResponse(BaseModel):
    status: str
    purge_after: datetime | None = None


class CloseRequest(BaseModel):
    confirm: Literal['CLOSE']


def _response(row):
    return LifecycleResponse(status=row.status, purge_after=row.purge_after) if row else LifecycleResponse(status='active')


def _locked_lifecycle(db, org_id):
    db.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))'),
               {'key': f'reink:lifecycle:{org_id}'})
    db.execute(insert(OrganizationLifecycle).values(org_id=org_id).on_conflict_do_nothing())
    return db.get(OrganizationLifecycle, org_id, populate_existing=True)


@router.get('/lifecycle', response_model=LifecycleResponse)
def lifecycle(db: Session = Depends(get_tenant_db), user: CurrentUser = Depends(get_current_user)):
    return _response(db.get(OrganizationLifecycle, user.org_id))


@router.post('/close', response_model=LifecycleResponse)
def close_organization(body: CloseRequest, db: Session = Depends(get_tenant_db),
                       user: CurrentUser = Depends(require_permission('organization:close'))):
    row = _locked_lifecycle(db, user.org_id)
    if row.status == 'purged':
        raise HTTPException(409, 'Organization has been purged')
    if row.status == 'active':
        if not settings.TRIAL_IDENTITY_HASH_KEY:
            raise HTTPException(503, 'Organization closure is not configured')
        row.status = 'closing'
        row.closure_requested_at = now(db)
        row.purge_after = row.closure_requested_at + timedelta(days=30)
        row.requested_by_hash = trial_user_hash(user.user_id, settings.TRIAL_IDENTITY_HASH_KEY)
    cancel_organization_extractions(db, user.org_id)
    response = _response(row)
    db.commit()
    return response


@router.post('/cancel-closure', response_model=LifecycleResponse)
def cancel_closure(db: Session = Depends(get_tenant_db),
                   user: CurrentUser = Depends(require_permission('organization:close'))):
    row = _locked_lifecycle(db, user.org_id)
    if row.status != 'closing' or now(db) >= row.purge_after:
        raise HTTPException(409, 'Closure can only be cancelled before the purge date')
    row.status = 'active'
    row.closure_requested_at = row.purge_after = row.requested_by_hash = None
    row.purge_step = row.last_purge_error = None
    row.purge_attempts = 0
    db.commit()
    return LifecycleResponse(status='active')
