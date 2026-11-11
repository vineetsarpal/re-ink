"""Atomic admission and settlement for extraction attempts.

Callers must keep the reservation and job transition in one database transaction.
No provider call may begin until its reservation has committed. Every terminal
transition, including timeout and deletion, must settle it. This module does not
connect itself to workflow dispatch; uploads remain gated until integration.
"""
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import load_only
from sqlalchemy.dialects.postgresql import insert

from app.models.extraction_quota import ExtractionRate, GlobalQuota, OrganizationQuota, QuotaReservation


@dataclass(frozen=True)
class Usage:
    monthly_successes: int
    monthly_attempts: int
    pending: int
    free_successes: int
    free_pending: int


def _month(at):
    at = at or datetime.now(timezone.utc)
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("Time must include a timezone")
    return at.astimezone(timezone.utc).date().replace(day=1)


def _locked_accounts(db, org_id, month):
    if not org_id:
        raise ValueError("Organization is required")
    # A single lock ordering avoids cross-tenant deadlocks and makes the global
    # trial cap safe under concurrent admissions.
    db.execute(insert(GlobalQuota).values(id=1, month=month, trial_successes=0, trial_pending=0).on_conflict_do_nothing())
    global_quota = db.scalar(select(GlobalQuota).where(GlobalQuota.id == 1).with_for_update())
    db.execute(insert(OrganizationQuota).values(org_id=org_id, month=month, monthly_successes=0, monthly_attempts=0, pending=0, free_successes=0, free_pending=0).on_conflict_do_nothing())
    org_quota = db.scalar(select(OrganizationQuota).where(OrganizationQuota.org_id == org_id).with_for_update())
    # A request may have captured its timestamp before waiting on the lock
    # across midnight; never move counters backwards into a previous month.
    month = max(month, global_quota.month, org_quota.month)
    if global_quota.month != month:
        global_quota.month, global_quota.trial_successes, global_quota.trial_starts = month, 0, 0
    if org_quota.month != month:
        org_quota.month, org_quota.monthly_successes, org_quota.monthly_attempts = month, 0, 0
    return global_quota, org_quota


def reserve_extraction(db, org_id, attempt_id, *, has_customer_key, global_trial_limit, global_trial_call_limit=None, monthly_limit=50, free_limit=5, attempt_limit=200, per_minute_limit=10, at=None):
    if (not attempt_id or len(attempt_id) > 128 or min(global_trial_limit, monthly_limit, free_limit, attempt_limit, per_minute_limit) < 0
            or (global_trial_call_limit is not None and global_trial_call_limit < 0)):
        raise ValueError("Invalid quota configuration or attempt")
    timestamp = at or datetime.now(timezone.utc)
    global_quota, org = _locked_accounts(db, org_id, _month(timestamp))
    existing = db.get(QuotaReservation, (org_id, attempt_id))
    if existing:
        if existing.status != "pending":
            raise HTTPException(409, "Extraction reservation already settled")
        return existing
    if org.monthly_successes + org.pending >= monthly_limit:
        raise HTTPException(429, "Monthly extraction limit reached")
    if org.monthly_attempts >= attempt_limit:
        raise HTTPException(429, "Monthly extraction attempt limit reached")
    window_start = timestamp.astimezone(timezone.utc).replace(second=0, microsecond=0)
    db.execute(insert(ExtractionRate).values(org_id=org_id, window_start=window_start, attempts=0).on_conflict_do_nothing())
    rate = db.scalar(select(ExtractionRate).where(ExtractionRate.org_id == org_id).with_for_update())
    if window_start > rate.window_start:
        rate.window_start, rate.attempts = window_start, 0
    if rate.attempts >= per_minute_limit:
        raise HTTPException(429, "Too many extraction attempts; try again shortly", headers={"Retry-After": "60"})
    funding = "customer" if has_customer_key else "trial"
    if funding == "trial":
        if global_trial_call_limit is not None and global_quota.trial_starts >= global_trial_call_limit:
            raise HTTPException(429, "Free extractions temporarily unavailable; add a LandingAI key")
        if org.free_successes + org.free_pending >= free_limit:
            raise HTTPException(429, "Free extractions exhausted; add a LandingAI key")
        if global_quota.trial_successes + global_quota.trial_pending >= global_trial_limit:
            raise HTTPException(429, "Free extractions temporarily unavailable; add a LandingAI key")
        org.free_pending += 1
        global_quota.trial_pending += 1
    org.pending += 1
    org.monthly_attempts += 1
    rate.attempts += 1
    reservation = QuotaReservation(org_id=org_id, attempt_id=attempt_id, funding=funding, status="pending")
    db.add(reservation)
    db.flush()
    return reservation


def settle_extraction(db, org_id, attempt_id, *, success, at=None):
    global_quota, org = _locked_accounts(db, org_id, _month(at))
    reservation = db.get(QuotaReservation, (org_id, attempt_id), options=[load_only(QuotaReservation.org_id, QuotaReservation.attempt_id, QuotaReservation.status, QuotaReservation.funding)])
    if not reservation:
        raise HTTPException(404, "Extraction reservation not found")
    status = "succeeded" if success else "failed"
    if reservation.status != "pending":
        if reservation.status != status:
            raise HTTPException(409, "Extraction reservation already settled")
        return reservation
    reservation.status = status
    reservation.credential_snapshot = None
    org.pending -= 1
    if reservation.funding == "trial":
        org.free_pending -= 1
        global_quota.trial_pending -= 1
        if success:
            org.free_successes += 1
            global_quota.trial_successes += 1
    if success:
        org.monthly_successes += 1
    db.flush()
    return reservation


def start_provider_call(db, org_id, attempt_id, *, global_trial_call_limit, at=None):
    """Count a provider start before it is authorized, including failed calls."""
    if global_trial_call_limit < 0:
        raise ValueError("Invalid trial provider-call limit")
    global_quota, _ = _locked_accounts(db, org_id, _month(at))
    reservation = db.get(QuotaReservation, (org_id, attempt_id))
    if not reservation or reservation.status != "pending":
        raise HTTPException(409, "Extraction reservation is not active")
    if reservation.provider_started:
        return
    if reservation.funding == "trial":
        if global_quota.trial_starts >= global_trial_call_limit:
            raise HTTPException(429, "Free extractions temporarily unavailable; add a LandingAI key")
        global_quota.trial_starts += 1
    reservation.provider_started = True
    db.flush()


def quota_usage(db, org_id, *, at=None):
    _, org = _locked_accounts(db, org_id, _month(at))
    return Usage(org.monthly_successes, org.monthly_attempts, org.pending, org.free_successes, org.free_pending)
