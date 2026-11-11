from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
import json
import threading
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.core.tenancy import bind_session_to_org
from app.models.extraction_job import ExtractionJob
from app.models.workflow import ExtractionAttempt
from app.services.cloudflare_coordinator import claim_preparation, checkpoint_terminal_event


@pytest.fixture
def unreserved_attempt(db_session):
    bind_session_to_org(db_session, "org-alpha")
    now = datetime.now(timezone.utc)
    db_session.add(ExtractionJob(job_id="job-a", org_id="org-alpha", status="queued", selected_attempt_id="attempt-a"))
    db_session.flush()
    db_session.add(ExtractionAttempt(attempt_id="attempt-a", job_id="job-a", org_id="org-alpha", number=1,
                                     status="queued", created_at=now, deadline_at=now + timedelta(minutes=5)))
    db_session.flush()
    return db_session


@pytest.fixture
def attempt(unreserved_attempt):
    from app.services.extraction_quota import reserve_extraction
    reserve_extraction(unreserved_attempt, "org-alpha", "attempt-a", has_customer_key=False, global_trial_limit=100)
    return unreserved_attempt


def test_redelivery_cannot_reacquire_a_started_provider_call(attempt):
    first = claim_preparation(attempt, "job-a", "attempt-a")
    second = claim_preparation(attempt, "job-a", "attempt-a")
    assert first["decision"] == "start"
    assert first["checkpoint_token"]
    assert second == {"decision": "in_progress"}


def test_existing_other_workflow_claim_is_never_taken_over(attempt):
    record = attempt.get(ExtractionAttempt, "attempt-a")
    record.execution_key = "other-execution"
    attempt.flush()
    assert claim_preparation(attempt, "job-a", "attempt-a") == {"decision": "closed"}


def test_terminal_checkpoint_is_replayed_on_redelivery(attempt):
    from app.services.extraction_quota import reserve_extraction, start_provider_call
    reserve_extraction(attempt, "org-alpha", "attempt-a", has_customer_key=False, global_trial_limit=100)
    start_provider_call(attempt, "org-alpha", "attempt-a", global_trial_call_limit=100)
    first = claim_preparation(attempt, "job-a", "attempt-a")
    event = {"schema_version": "1", "job_id": "job-a", "attempt_id": "attempt-a", "event_id": "terminal", "status": "completed", "result": {"contract_data": {"contract_name": "Treaty"}, "parties_data": []}}
    checkpoint_terminal_event(attempt, "job-a", "attempt-a", first["checkpoint_token"], json.dumps(event).encode())
    assert claim_preparation(attempt, "job-a", "attempt-a") == {"decision": "terminal", "event": event}


def test_other_organization_cannot_access_or_claim_job(attempt):
    bind_session_to_org(attempt, "org-beta")
    with pytest.raises(HTTPException) as exc:
        claim_preparation(attempt, "job-a", "attempt-a")
    assert exc.value.status_code == 404


def test_checkpoint_requires_grant_and_cannot_be_replaced(attempt):
    grant = claim_preparation(attempt, "job-a", "attempt-a")
    event = {"schema_version": "1", "job_id": "job-a", "attempt_id": "attempt-a", "event_id": "terminal", "status": "failed", "error": {"code": "EXTRACTION_FAILED", "message": "Extraction failed.", "retryable": False}}
    payload = json.dumps(event).encode()
    with pytest.raises(HTTPException) as exc:
        checkpoint_terminal_event(attempt, "job-a", "attempt-a", "wrong-token", payload)
    assert exc.value.status_code == 403
    assert checkpoint_terminal_event(attempt, "job-a", "attempt-a", grant["checkpoint_token"], payload)
    assert checkpoint_terminal_event(attempt, "job-a", "attempt-a", grant["checkpoint_token"], payload)
    event["error"]["message"] = "A different result."
    with pytest.raises(HTTPException) as exc:
        checkpoint_terminal_event(attempt, "job-a", "attempt-a", grant["checkpoint_token"], json.dumps(event).encode())
    assert exc.value.status_code == 409


def test_concurrent_claims_allow_only_one_provider_call(restricted_engine, preserve_global_quota):
    from app.models.extraction_quota import QuotaReservation, OrganizationQuota, ExtractionRate
    from app.services.extraction_quota import reserve_extraction
    suffix = uuid.uuid4().hex
    org, job_id, attempt_id = f"org-{suffix}", f"job-{suffix}", f"attempt-{suffix}"
    now = datetime.now(timezone.utc)
    with Session(restricted_engine) as session:
        bind_session_to_org(session, org)
        session.add(ExtractionJob(job_id=job_id, org_id=org, status="queued", selected_attempt_id=attempt_id))
        session.flush()
        session.add(ExtractionAttempt(attempt_id=attempt_id, job_id=job_id, org_id=org, number=1,
                                      status="queued", created_at=now, deadline_at=now + timedelta(minutes=5)))
        reserve_extraction(session, org, attempt_id, has_customer_key=True, global_trial_limit=100)
        session.commit()
    barrier = threading.Barrier(2)

    def claim():
        with Session(restricted_engine) as session:
            bind_session_to_org(session, org)
            barrier.wait(timeout=5)
            result = claim_preparation(session, job_id, attempt_id)
            session.commit()
            return result["decision"]

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            decisions = list(pool.map(lambda _: claim(), range(2)))
        assert sorted(decisions) == ["in_progress", "start"]
    finally:
        with Session(restricted_engine) as session:
            bind_session_to_org(session, org)
            for model in (QuotaReservation, OrganizationQuota, ExtractionRate):
                session.execute(delete(model).where(model.org_id == org))
            session.execute(delete(ExtractionAttempt).where(ExtractionAttempt.attempt_id == attempt_id))
            session.execute(delete(ExtractionJob).where(ExtractionJob.job_id == job_id))
            session.commit()


def test_concurrent_provider_authorizations_count_only_once(restricted_engine, monkeypatch, preserve_global_quota):
    from app.core.config import settings
    from app.models.extraction_quota import GlobalQuota, OrganizationQuota, QuotaReservation, ExtractionRate
    from app.services.extraction_quota import reserve_extraction
    from app.services.cloudflare_coordinator import authorize_provider_start
    monkeypatch.setattr(settings, "EXTRACTION_GLOBAL_TRIAL_CALL_MONTHLY_LIMIT", 100)
    suffix = uuid.uuid4().hex
    org, job_id, attempt_id = f"org-{suffix}", f"job-{suffix}", f"attempt-{suffix}"
    now = datetime.now(timezone.utc)
    with Session(restricted_engine) as session:
        bind_session_to_org(session, org)
        session.add(ExtractionJob(job_id=job_id, org_id=org, status="queued", selected_attempt_id=attempt_id))
        session.flush()
        session.add(ExtractionAttempt(attempt_id=attempt_id, job_id=job_id, org_id=org, number=1,
                                      status="queued", created_at=now, deadline_at=now + timedelta(minutes=5)))
        session.flush()
        reserve_extraction(session, org, attempt_id, has_customer_key=False, global_trial_limit=100)
        token = claim_preparation(session, job_id, attempt_id)["checkpoint_token"]
        before = session.get(GlobalQuota, 1).trial_starts
        session.commit()
    barrier = threading.Barrier(2)

    def start():
        with Session(restricted_engine) as session:
            bind_session_to_org(session, org)
            barrier.wait(timeout=5)
            try:
                assert authorize_provider_start(session, job_id, attempt_id, token)
                session.commit()
                return 200
            except HTTPException as exc:
                session.rollback()
                return exc.status_code

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(lambda _: start(), range(2))) == [200, 409]
        with Session(restricted_engine) as session:
            bind_session_to_org(session, org)
            assert session.get(GlobalQuota, 1).trial_starts == before + 1
    finally:
        with Session(restricted_engine) as session:
            bind_session_to_org(session, org)
            session.execute(delete(QuotaReservation).where(QuotaReservation.attempt_id == attempt_id))
            session.execute(delete(OrganizationQuota).where(OrganizationQuota.org_id == org))
            session.execute(delete(ExtractionRate).where(ExtractionRate.org_id == org))
            session.execute(delete(ExtractionAttempt).where(ExtractionAttempt.attempt_id == attempt_id))
            session.execute(delete(ExtractionJob).where(ExtractionJob.job_id == job_id))
            session.commit()


def test_completed_checkpoint_requires_counted_provider_start(attempt):
    from app.services.extraction_quota import reserve_extraction
    reserve_extraction(attempt, "org-alpha", "attempt-a", has_customer_key=False, global_trial_limit=100)
    grant = claim_preparation(attempt, "job-a", "attempt-a")
    event = {"schema_version": "1", "job_id": "job-a", "attempt_id": "attempt-a", "event_id": "terminal", "status": "completed", "result": {"contract_data": {"contract_name": "Treaty"}, "parties_data": []}}
    with pytest.raises(HTTPException) as exc:
        checkpoint_terminal_event(attempt, "job-a", "attempt-a", grant["checkpoint_token"], json.dumps(event).encode())
    assert exc.value.status_code == 409


@pytest.mark.parametrize("quota_enabled", [False, True])
def test_missing_reservation_refuses_preparation_before_claim(unreserved_attempt, monkeypatch, quota_enabled):
    attempt = unreserved_attempt
    from app.core.config import settings
    from app.models.cloudflare_execution import CloudflareExecution

    monkeypatch.setattr(settings, "EXTRACTION_QUOTA_ENABLED", quota_enabled)
    with pytest.raises(HTTPException) as exc:
        claim_preparation(attempt, "job-a", "attempt-a")
    assert exc.value.status_code == 409
    assert exc.value.detail == "Extraction reservation unavailable"
    assert attempt.get(CloudflareExecution, "attempt-a") is None
    record = attempt.get(ExtractionAttempt, "attempt-a")
    assert record.execution_key is None
    assert record.accepted_at is None
    assert record.status == "queued"
    assert attempt.get(ExtractionJob, "job-a").status == "queued"
