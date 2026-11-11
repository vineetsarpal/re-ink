"""Disabled-by-default scheduled outbox dispatch for a trusted scheduler."""
from dataclasses import dataclass, field
from hmac import compare_digest
from typing import Callable
from time import monotonic

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.cloudflare_dispatch import CloudflareQueueConfig, dispatch_cloudflare_once
from app.core.config import settings, _decoded_secret
from app.core.cloudflare_runtime import dispatch_factory, require_enabled

router = APIRouter(prefix="/maintenance", tags=["maintenance"])
_MAX_DISPATCHES = 5
_BATCH_BUDGET_SECONDS = 15


@dataclass(frozen=True)
class MaintenanceSettings:
    token: str = field(repr=False)
    queue: CloudflareQueueConfig = field(repr=False)


def maintenance_settings() -> MaintenanceSettings:
    require_enabled()
    return MaintenanceSettings(settings.CLOUDFLARE_DISPATCH_TOKEN, CloudflareQueueConfig(
        settings.CLOUDFLARE_ACCOUNT_ID, settings.CLOUDFLARE_QUEUE_ID,
        settings.CLOUDFLARE_QUEUE_API_TOKEN, _decoded_secret(settings.CLOUDFLARE_CAPABILITY_KEY),
        settings.WORKFLOW_QUEUE_TIMEOUT_SECONDS, settings.WORKFLOW_PROCESSING_TIMEOUT_SECONDS))


def maintenance_factory() -> Callable[[], Session]:
    # Never substitute the ordinary app's connection: discovery uses a
    # separate, explicitly provisioned machine identity.
    return dispatch_factory()


def authorize_scheduler(authorization: str | None = Header(default=None),
                        settings: MaintenanceSettings = Depends(maintenance_settings)) -> MaintenanceSettings:
    if len(settings.token) < 32:
        raise HTTPException(503, "Cloudflare dispatch is not configured")
    scheme, _, credential = (authorization or "").partition(" ")
    if (scheme.lower() != "bearer" or len(credential) > 512 or not credential or
            not compare_digest(credential.encode(), settings.token.encode())):
        raise HTTPException(401, "Invalid machine credentials")
    return settings


@router.post("/cloudflare-dispatch")
def dispatch_due(settings: MaintenanceSettings = Depends(authorize_scheduler),
                 factory: Callable[[], Session] = Depends(maintenance_factory)):
    """Dispatch a bounded batch; callers do not choose the organization."""
    delivered = 0
    deadline = monotonic() + _BATCH_BUDGET_SECONDS
    with httpx.Client(timeout=3, follow_redirects=False) as client:
        for _ in range(_MAX_DISPATCHES):
            if monotonic() >= deadline:
                break
            with factory() as db:
                db.execute(text("SET LOCAL statement_timeout = '3s'"))
                org_id = db.scalar(text("SELECT public.reink_next_due_dispatch_org()"))
            if not org_id:
                break
            if not dispatch_cloudflare_once(factory, org_id, settings.queue, client):
                # A concurrent invocation may have acquired the candidate.
                break
            delivered += 1
    return {"attempted": delivered}
