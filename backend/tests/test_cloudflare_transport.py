from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.tenancy import bind_session_to_org
from app.models.extraction_job import ExtractionJob
from app.models.workflow import ExtractionAttempt, WorkflowOutbox
from app.api.endpoints.cloudflare import router, CloudflareTransportSettings, transport_settings, session_factory
from app.services.dispatch_capability import issue_capability

SIGNING_KEY = b"s" * 32
WORKER_TOKEN = "worker-token-" + "x" * 32


@pytest.fixture
def machine_client(db_session):
    bind_session_to_org(db_session, "org-alpha")
    now = datetime.now(timezone.utc)
    db_session.add(ExtractionJob(job_id="job-a", org_id="org-alpha", status="queued", selected_attempt_id="attempt-a", filename="contract.pdf", content_type="application/pdf", storage_key="object-a", size_bytes=7, sha256="a" * 64))
    db_session.flush()
    db_session.add(ExtractionAttempt(attempt_id="attempt-a", job_id="job-a", org_id="org-alpha", number=1,
                                     status="queued", created_at=now, deadline_at=now + timedelta(minutes=5)))
    db_session.flush()
    db_session.add(WorkflowOutbox(attempt_id="attempt-a", org_id="org-alpha", payload={}, next_delivery_at=now, delivery_count=0))
    db_session.commit()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[transport_settings] = lambda: CloudflareTransportSettings(WORKER_TOKEN, [SIGNING_KEY])
    app.dependency_overrides[session_factory] = lambda: lambda: db_session
    return TestClient(app)


@pytest.fixture
def machine_headers():
    return {"X-Extraction-Protocol": "2", "Authorization": f"Bearer {WORKER_TOKEN}",
            "X-Dispatch-Capability": issue_capability(SIGNING_KEY, "org-alpha", "job-a", "attempt-a", ttl_seconds=300)}


@pytest.fixture
def reserved_machine(machine_client, db_session):
    from app.services.extraction_quota import reserve_extraction
    bind_session_to_org(db_session, "org-alpha")
    reserve_extraction(db_session, "org-alpha", "attempt-a", has_customer_key=False, global_trial_limit=100)
    db_session.commit()
    return machine_client


def test_machine_claim_requires_both_worker_credential_and_job_capability(machine_client):
    path = "/cloudflare/jobs/job-a/attempts/attempt-a/claim"
    capability = issue_capability(SIGNING_KEY, "org-alpha", "job-a", "attempt-a", ttl_seconds=300)
    assert machine_client.post(path, headers={"X-Dispatch-Capability": capability}).status_code == 401
    assert machine_client.post(path, headers={"X-Extraction-Protocol": "2", "Authorization": f"Bearer {WORKER_TOKEN}"}).status_code == 401
    response = machine_client.post(path, headers={"X-Extraction-Protocol": "2", "Authorization": f"Bearer {WORKER_TOKEN}", "X-Dispatch-Capability": capability})
    assert response.status_code == 200, response.text
    assert response.json()["decision"] == "start"


@pytest.mark.skip(reason="Organization closure is not enabled in the production-based checkout")
def test_closed_organization_cannot_claim_extraction(machine_client, db_session):
    from app.services.organization_lifecycle import close_organization

    close_organization(db_session, "org-alpha")
    db_session.commit()
    capability = issue_capability(SIGNING_KEY, "org-alpha", "job-a", "attempt-a", ttl_seconds=300)
    response = machine_client.post(
        "/cloudflare/jobs/job-a/attempts/attempt-a/claim",
        headers={"X-Extraction-Protocol": "2", "Authorization": f"Bearer {WORKER_TOKEN}", "X-Dispatch-Capability": capability},
    )
    assert response.status_code == 403


def test_signed_capability_cannot_cross_tenant_or_change_job(machine_client):
    path = "/cloudflare/jobs/job-a/attempts/attempt-a/claim"
    other_org = issue_capability(SIGNING_KEY, "org-beta", "job-a", "attempt-a", ttl_seconds=300)
    headers = {"X-Extraction-Protocol": "2", "Authorization": f"Bearer {WORKER_TOKEN}", "X-Dispatch-Capability": other_org}
    assert machine_client.post(path, headers=headers).status_code == 404
    wrong_job = issue_capability(SIGNING_KEY, "org-alpha", "job-b", "attempt-a", ttl_seconds=300)
    headers["X-Dispatch-Capability"] = wrong_job
    assert machine_client.post(path, headers=headers).status_code == 401


def test_owner_checkpoints_and_redelivery_replays_terminal_result(machine_client, machine_headers):
    base = "/cloudflare/jobs/job-a/attempts/attempt-a"
    headers = machine_headers.copy()
    claim = machine_client.post(base + "/claim", headers=headers)
    assert claim.status_code == 200, claim.text
    event = {"schema_version": "1", "job_id": "job-a", "attempt_id": "attempt-a", "event_id": "terminal", "status": "failed", "error": {"code": "EXTRACTION_FAILED", "message": "Extraction failed.", "retryable": False}}
    bad_headers = {**headers, "X-Checkpoint-Token": "wrong"}
    assert machine_client.post(base + "/checkpoint", headers=bad_headers, json=event).status_code == 403
    headers["X-Checkpoint-Token"] = claim.json()["checkpoint_token"]
    stored = machine_client.post(base + "/checkpoint", headers=headers, json=event)
    assert stored.status_code == 200, stored.text
    replay = machine_client.post(base + "/claim", headers=headers)
    assert replay.json() == {"decision": "terminal", "event": event}


def test_delivery_applies_checkpoint_once_and_acknowledges_replay(machine_client, db_session, machine_headers):
    base = "/cloudflare/jobs/job-a/attempts/attempt-a"
    headers = machine_headers.copy()
    claim = machine_client.post(base + "/claim", headers=headers)
    headers["X-Checkpoint-Token"] = claim.json()["checkpoint_token"]
    event = {"schema_version": "1", "job_id": "job-a", "attempt_id": "attempt-a", "event_id": "terminal", "status": "failed", "error": {"code": "EXTRACTION_FAILED", "message": "Extraction failed.", "retryable": False}}
    assert machine_client.post(base + "/checkpoint", headers=headers, json=event).status_code == 200
    for _ in range(2):
        response = machine_client.post(base + "/deliver", headers=headers)
        assert response.status_code == 200, response.text
        assert response.json() == {"schema_version": "1", "event_id": "terminal", "status": "acknowledged"}
    bind_session_to_org(db_session, "org-alpha")
    assert db_session.get(ExtractionJob, "job-a").status == "failed"


def test_only_claim_owner_can_fetch_attempt_credential(machine_client, monkeypatch, machine_headers):
    import app.api.endpoints.cloudflare as cloudflare
    calls = []
    monkeypatch.setattr(cloudflare, "get_attempt_credential", lambda *args: calls.append(args) or "landing-secret")
    base = "/cloudflare/jobs/job-a/attempts/attempt-a"
    headers = machine_headers.copy()
    claim = machine_client.post(base + "/claim", headers=headers)
    assert claim.status_code == 200
    assert machine_client.get(base + "/credential", headers={**headers, "X-Checkpoint-Token": "wrong"}).status_code == 403
    assert calls == []
    headers["X-Checkpoint-Token"] = claim.json()["checkpoint_token"]
    response = machine_client.get(base + "/credential", headers=headers)
    assert response.status_code == 200
    assert response.json() == {"api_key": "landing-secret"}
    assert response.headers["cache-control"] == "no-store"


def test_only_claim_owner_can_fetch_original_document(machine_client, monkeypatch, machine_headers):
    import app.api.endpoints.cloudflare as cloudflare
    calls = []
    monkeypatch.setattr(cloudflare.document_service, "read_original", lambda original: calls.append(original.org_id) or b"fixture")
    base = "/cloudflare/jobs/job-a/attempts/attempt-a"
    headers = machine_headers.copy()
    claim = machine_client.post(base + "/claim", headers=headers)
    assert machine_client.get(base + "/document", headers={**headers, "X-Checkpoint-Token": "wrong"}).status_code == 403
    assert calls == []
    headers["X-Checkpoint-Token"] = claim.json()["checkpoint_token"]
    response = machine_client.get(base + "/document", headers=headers)
    assert response.status_code == 200
    assert response.content == b"fixture"
    assert response.headers["cache-control"] == "no-store"
    assert calls == ["org-alpha"]


def test_document_is_not_returned_if_attempt_ends_during_storage_read(machine_client, db_session, monkeypatch, machine_headers):
    import app.api.endpoints.cloudflare as cloudflare
    def finish_during_read(original):
        db_session.get(ExtractionAttempt, "attempt-a").status = "failed"
        db_session.commit()
        return b"private-document"
    monkeypatch.setattr(cloudflare.document_service, "read_original", finish_during_read)
    base = "/cloudflare/jobs/job-a/attempts/attempt-a"
    headers = machine_headers.copy()
    claim = machine_client.post(base + "/claim", headers=headers)
    headers["X-Checkpoint-Token"] = claim.json()["checkpoint_token"]
    response = machine_client.get(base + "/document", headers=headers)
    assert response.status_code == 409
    assert b"private-document" not in response.content


def test_expired_attempt_transition_is_committed_before_rejection(machine_client, db_session, machine_headers):
    base = "/cloudflare/jobs/job-a/attempts/attempt-a"
    headers = machine_headers.copy()
    claim = machine_client.post(base + "/claim", headers=headers)
    headers["X-Checkpoint-Token"] = claim.json()["checkpoint_token"]
    bind_session_to_org(db_session, "org-alpha")
    attempt = db_session.get(ExtractionAttempt, "attempt-a")
    attempt.deadline_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db_session.commit()
    response = machine_client.get(base + "/credential", headers=headers)
    assert response.status_code == 409
    bind_session_to_org(db_session, "org-alpha")
    assert db_session.get(ExtractionAttempt, "attempt-a").status == "timed_out"


def test_expired_checkpoint_commits_timeout_before_rejection(machine_client, db_session, machine_headers):
    base = "/cloudflare/jobs/job-a/attempts/attempt-a"
    headers = machine_headers.copy()
    claim = machine_client.post(base + "/claim", headers=headers)
    headers["X-Checkpoint-Token"] = claim.json()["checkpoint_token"]
    bind_session_to_org(db_session, "org-alpha")
    db_session.get(ExtractionAttempt, "attempt-a").deadline_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db_session.commit()
    event = {"schema_version": "1", "job_id": "job-a", "attempt_id": "attempt-a", "event_id": "terminal", "status": "failed", "error": {"code": "EXTRACTION_FAILED", "message": "Extraction failed.", "retryable": False}}
    assert machine_client.post(base + "/checkpoint", headers=headers, json=event).status_code == 409
    bind_session_to_org(db_session, "org-alpha")
    assert db_session.get(ExtractionAttempt, "attempt-a").status == "timed_out"


def test_preparation_does_not_spend_start_and_provider_authorization_is_one_shot(reserved_machine, db_session, monkeypatch, machine_headers):
    from app.core.config import settings
    from app.models.extraction_quota import GlobalQuota, QuotaReservation
    monkeypatch.setattr(settings, "EXTRACTION_GLOBAL_TRIAL_CALL_MONTHLY_LIMIT", 100)
    machine_client = reserved_machine
    base = "/cloudflare/jobs/job-a/attempts/attempt-a"
    headers = machine_headers.copy()
    grant = machine_client.post(base + "/claim", headers=headers)
    assert grant.status_code == 200
    bind_session_to_org(db_session, "org-alpha")
    assert db_session.get(GlobalQuota, 1).trial_starts == 0
    assert not db_session.get(QuotaReservation, ("org-alpha", "attempt-a")).provider_started
    headers["X-Checkpoint-Token"] = "wrong"
    assert machine_client.post(base + "/provider-start", headers=headers).status_code == 403
    headers["X-Checkpoint-Token"] = grant.json()["checkpoint_token"]
    started = machine_client.post(base + "/provider-start", headers=headers)
    assert started.status_code == 200, started.text
    assert started.json() == {"authorized": True}
    assert machine_client.post(base + "/provider-start", headers=headers).status_code == 409
    bind_session_to_org(db_session, "org-alpha")
    assert db_session.get(GlobalQuota, 1).trial_starts == 1


@pytest.mark.parametrize("cap", [0, 100])
def test_preparation_failure_or_cap_denial_settles_without_spending_a_start(reserved_machine, db_session, monkeypatch, cap, machine_headers):
    from app.core.config import settings
    from app.models.extraction_quota import GlobalQuota, QuotaReservation
    monkeypatch.setattr(settings, "EXTRACTION_GLOBAL_TRIAL_CALL_MONTHLY_LIMIT", cap)
    machine_client = reserved_machine
    base = "/cloudflare/jobs/job-a/attempts/attempt-a"
    headers = machine_headers.copy()
    grant = machine_client.post(base + "/claim", headers=headers)
    headers["X-Checkpoint-Token"] = grant.json()["checkpoint_token"]
    if cap == 0:
        assert machine_client.post(base + "/provider-start", headers=headers).status_code == 429
    event = {"schema_version": "1", "job_id": "job-a", "attempt_id": "attempt-a", "event_id": "terminal", "status": "failed", "error": {"code": "PREPARATION_FAILED", "message": "Preparation failed.", "retryable": True}}
    assert machine_client.post(base + "/checkpoint", headers=headers, json=event).status_code == 200
    assert machine_client.post(base + "/provider-start", headers=headers).status_code == 403
    assert machine_client.post(base + "/deliver", headers=headers).status_code == 200
    bind_session_to_org(db_session, "org-alpha")
    assert db_session.get(GlobalQuota, 1).trial_starts == 0
    assert db_session.get(GlobalQuota, 1).trial_pending == 0
    assert db_session.get(QuotaReservation, ("org-alpha", "attempt-a")).status == "failed"


@pytest.mark.parametrize("version", [None, "1", "future"])
def test_incompatible_worker_cannot_claim(reserved_machine, db_session, version):
    machine_client = reserved_machine
    from app.models.cloudflare_execution import CloudflareExecution
    headers = {"Authorization": f"Bearer {WORKER_TOKEN}", "X-Dispatch-Capability": issue_capability(SIGNING_KEY, "org-alpha", "job-a", "attempt-a", ttl_seconds=300)}
    if version is not None:
        headers["X-Extraction-Protocol"] = version
    response = machine_client.post("/cloudflare/jobs/job-a/attempts/attempt-a/claim", headers=headers)
    assert response.status_code == 409, response.text
    bind_session_to_org(db_session, "org-alpha")
    assert db_session.get(CloudflareExecution, "attempt-a") is None
    assert db_session.get(ExtractionJob, "job-a").status == "queued"
    from app.models.extraction_quota import GlobalQuota, QuotaReservation
    assert db_session.get(GlobalQuota, 1).trial_starts == 0
    assert not db_session.get(QuotaReservation, ("org-alpha", "attempt-a")).provider_started


def test_protocol_probe_does_not_claim(machine_client, db_session):
    from app.models.cloudflare_execution import CloudflareExecution
    headers = {"Authorization": f"Bearer {WORKER_TOKEN}", "X-Dispatch-Capability": issue_capability(SIGNING_KEY, "org-alpha", "job-a", "attempt-a", ttl_seconds=300)}
    response = machine_client.get("/cloudflare/jobs/job-a/attempts/attempt-a/protocol", headers=headers)
    assert response.status_code == 200, response.text
    assert response.json() == {"protocol_version": "2"}
    bind_session_to_org(db_session, "org-alpha")
    assert db_session.get(CloudflareExecution, "attempt-a") is None
