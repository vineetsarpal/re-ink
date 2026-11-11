"""Tenant-scoped transactional outbox delivery to Cloudflare Queues.

This is an integration foundation, not a scheduler. The caller must derive the
tenant from trusted application state, and ensure periodic redelivery across
all tenants. No secret or capability is persisted in the outbox.
"""
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
import math
import random
import re

import httpx
from fastapi import HTTPException
from sqlalchemy import event, select

from app.models.workflow import ExtractionAttempt, WorkflowOutbox
from app.services.dispatch_capability import MAX_TTL_SECONDS, issue_capability
from app.services.workflow_service import lease_dispatch, now


def _retry_after(value):
    if not value:
        return None
    try:
        seconds = float(value)
        return min(60, max(0, seconds)) if math.isfinite(seconds) else None
    except ValueError:
        try:
            return min(60, max(0, (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds()))
        except (TypeError, ValueError, OverflowError):
            return None


@dataclass(frozen=True)
class CloudflareQueueConfig:
    account_id: str
    queue_id: str
    api_token: str = field(repr=False)
    capability_key: bytes = field(repr=False)
    queue_timeout: int
    processing_timeout: int

    def __post_init__(self):
        if (not re.fullmatch(r"[0-9a-fA-F]{32}", self.account_id)
                or not re.fullmatch(r"[0-9a-fA-F]{32}", self.queue_id)
                or not self.api_token or self.api_token.strip() != self.api_token
                or not isinstance(self.capability_key, bytes) or len(self.capability_key) < 32
                or type(self.queue_timeout) is not int or self.queue_timeout <= 0
                or type(self.processing_timeout) is not int or self.processing_timeout <= 0
                or self.queue_timeout + self.processing_timeout + 60 > MAX_TTL_SECONDS):
            raise ValueError("Invalid Cloudflare queue configuration")

    @property
    def url(self):
        return f"https://api.cloudflare.com/client/v4/accounts/{self.account_id}/queues/{self.queue_id}/messages"


@contextmanager
def _tenant_session(factory, org_id):
    if not isinstance(org_id, str) or not org_id.strip() or len(org_id) > 255:
        raise ValueError("Invalid organization scope")
    db = factory()

    @event.listens_for(db, "after_begin")
    def _bind(session, transaction, connection):
        connection.exec_driver_sql("SELECT set_config('app.current_org', %s, true)", (org_id,))
        connection.exec_driver_sql("SET LOCAL lock_timeout = '2s'")
        connection.exec_driver_sql("SET LOCAL statement_timeout = '3s'")

    try:
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        event.remove(db, "after_begin", _bind)
        db.close()


def _finish(db, lease, *, accepted, retry_after):
    # Only lock the outbox row. A deleted, expired or replaced attempt cannot
    # pass the coordinator's subsequent claim, even if a message was sent.
    row = db.scalar(select(WorkflowOutbox).where(WorkflowOutbox.attempt_id == lease["attempt_id"]).with_for_update().execution_options(populate_existing=True))
    if not row or row.lease_token != lease["token"] or row.lease_until is None or row.lease_until <= now(db):
        return False
    timestamp = now(db)
    if accepted:
        # Queue admission is not extraction start.
        row.acknowledged_at = timestamp
    else:
        deadline = db.scalar(select(ExtractionAttempt.deadline_at).where(ExtractionAttempt.attempt_id == lease["attempt_id"]))
        if deadline is None:
            return False
        delay = min(60, 5 * 2 ** min(lease["count"] - 1, 4))
        if retry_after is not None:
            delay = min(60, max(0, retry_after))
        row.next_delivery_at = min(deadline, timestamp + timedelta(seconds=delay + random.uniform(0, 1)))
        row.last_error = "DELIVERY_RETRY"
    row.lease_token = row.lease_until = None
    db.flush()
    return True


def dispatch_cloudflare_once(factory, org_id: str, config: CloudflareQueueConfig, client: httpx.Client) -> bool:
    """Send at most one leased message for a *trusted* organization.

    Enqueue outcomes can be ambiguous; redelivery may submit a duplicate, so
    the consumer must fence paid provider calls using the attempt identity.
    """
    with _tenant_session(factory, org_id) as db:
        lease = lease_dispatch(db)
    if not lease:
        return False
    payload = dict(lease["payload"])
    payload["capability"] = issue_capability(config.capability_key, org_id, payload["job_id"], payload["attempt_id"], ttl_seconds=MAX_TTL_SECONDS)
    accepted = False
    retry_after = None
    try:
        response = client.post(config.url, headers={"Authorization": f"Bearer {config.api_token}"},
                               json={"body": payload, "content_type": "json"}, follow_redirects=False)
        retry_after = _retry_after(response.headers.get("Retry-After"))
        if response.status_code == 200:
            try:
                accepted = response.json().get("success") is True
            except (ValueError, AttributeError):
                pass
    except httpx.HTTPError:
        pass
    with _tenant_session(factory, org_id) as db:
        try:
            # Configuration/network failures remain retryable until the job
            # deadline. Expiry settlement belongs to the separate sweeper.
            _finish(db, lease, accepted=accepted, retry_after=retry_after)
        except HTTPException as exc:
            if exc.status_code not in (404, 409, 410):
                raise
    return True
