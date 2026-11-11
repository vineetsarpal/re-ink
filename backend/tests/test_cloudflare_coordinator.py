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
from app.services.cloudflare_coordinator import claim_provider_call, checkpoint_terminal_event


@pytest.fixture
def attempt(db_session):
    bind_session_to_org(db_session, "org-alpha")
    now = datetime.now(timezone.utc)
    db_session.add(ExtractionJob(job_id="job-a", org_id="org-alpha", status="queued", selected_attempt_id="attempt-a"))
    db_session.flush()
    db_session.add(ExtractionAttempt(attempt_id="attempt-a", job_id="job-a", org_id="org-alpha", number=1,
                                     status="queued", created_at=now, deadline_at=now + timedelta(minutes=5)))
    db_session.flush()
    return db_session


def test_redelivery_cannot_reacquire_a_started_provider_call(attempt):
    first = claim_provider_call(attempt, "job-a", "attempt-a")
    second = claim_provider_call(attempt, "job-a", "attempt-a")
    assert first["decision"] == "start"
    assert first["checkpoint_token"]
    assert second == {"decision": "in_progress"}


def test_existing_other_workflow_claim_is_never_taken_over(attempt):
    record = attempt.get(ExtractionAttempt, "attempt-a")
    record.execution_key = "other-execution"
    attempt.flush()
    assert claim_provider_call(attempt, "job-a", "attempt-a") == {"decision": "closed"}


def test_terminal_checkpoint_is_replayed_on_redelivery(attempt):
    first = claim_provider_call(attempt, "job-a", "attempt-a")
    event = {"schema_version": "1", "job_id": "job-a", "attempt_id": "attempt-a", "event_id": "terminal", "status": "completed", "result": {"contract_data": {"contract_name": "Treaty"}, "parties_data": []}}
    checkpoint_terminal_event(attempt, "job-a", "attempt-a", first["checkpoint_token"], json.dumps(event).encode())
    assert claim_provider_call(attempt, "job-a", "attempt-a") == {"decision": "terminal", "event": event}


def test_other_organization_cannot_access_or_claim_job(attempt):
    bind_session_to_org(attempt, "org-beta")
    with pytest.raises(HTTPException) as exc:
        claim_provider_call(attempt, "job-a", "attempt-a")
    assert exc.value.status_code == 404


def test_checkpoint_requires_grant_and_cannot_be_replaced(attempt):
    grant = claim_provider_call(attempt, "job-a", "attempt-a")
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


def test_concurrent_claims_allow_only_one_provider_call(restricted_engine):
    suffix = uuid.uuid4().hex
    org, job_id, attempt_id = f"org-{suffix}", f"job-{suffix}", f"attempt-{suffix}"
    now = datetime.now(timezone.utc)
    with Session(restricted_engine) as session:
        bind_session_to_org(session, org)
        session.add(ExtractionJob(job_id=job_id, org_id=org, status="queued", selected_attempt_id=attempt_id))
        session.flush()
        session.add(ExtractionAttempt(attempt_id=attempt_id, job_id=job_id, org_id=org, number=1,
                                      status="queued", created_at=now, deadline_at=now + timedelta(minutes=5)))
        session.commit()
    barrier = threading.Barrier(2)

    def claim():
        with Session(restricted_engine) as session:
            bind_session_to_org(session, org)
            barrier.wait(timeout=5)
            result = claim_provider_call(session, job_id, attempt_id)
            session.commit()
            return result["decision"]

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            decisions = list(pool.map(lambda _: claim(), range(2)))
        assert sorted(decisions) == ["in_progress", "start"]
    finally:
        with Session(restricted_engine) as session:
            bind_session_to_org(session, org)
            session.execute(delete(ExtractionAttempt).where(ExtractionAttempt.attempt_id == attempt_id))
            session.execute(delete(ExtractionJob).where(ExtractionJob.job_id == job_id))
            session.commit()
