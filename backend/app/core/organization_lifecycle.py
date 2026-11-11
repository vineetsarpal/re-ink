from fastapi import Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.auth import CurrentUser, get_current_user
from app.db.database import get_db
from app.models.organization_lifecycle import OrganizationLifecycle

EXEMPT_ROUTES = {
    ('GET', '/api/organization/lifecycle'),
    ('POST', '/api/organization/close'),
    ('POST', '/api/organization/cancel-closure'),
    ('POST', '/api/members/me/leave'),
    ('GET', '/api/system/config'),
}


def require_active_organization(request: Request, user: CurrentUser = Depends(get_current_user),
                                db: Session = Depends(get_db)):
    if not user.org_id or (request.method, request.scope['route'].path) in EXEMPT_ROUTES:
        return
    db.execute(text('SELECT pg_advisory_xact_lock_shared(hashtextextended(:key, 0))'),
               {'key': f'reink:lifecycle:{user.org_id}'})
    row = db.get(OrganizationLifecycle, user.org_id, populate_existing=True)
    if row and row.status != 'active':
        raise HTTPException(423, {'code': 'ORGANIZATION_CLOSING' if row.status == 'closing' else 'ORGANIZATION_PURGED',
                                 'purge_after': row.purge_after.isoformat() if row.purge_after else None})
