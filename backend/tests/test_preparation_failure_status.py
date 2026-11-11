"""Public status and retry contract for failures before provider execution."""
from uuid import uuid4

import pytest

from app.core.config import settings
from app.schemas.workflow import EVENT_ADAPTER
from app.services import workflow_service


@pytest.fixture
def failed_job(as_org, db_session, monkeypatch):
    def create(retryable=True):
        org = "preparation-ui-" + uuid4().hex
        monkeypatch.setattr(settings, "CLOUDFLARE_TRIAL_ENABLED", True)
        monkeypatch.setattr(settings, "TRIAL_ALLOWED_ORGANIZATION_IDS", [org])
        client = as_org(org)
        assert client.post("/api/provider-credentials/landingai/acknowledgment").status_code == 200
        job = workflow_service.create_workflow_job(db_session, {
            "job_id": uuid4().hex, "filename": "synthetic.pdf", "storage_key": uuid4().hex,
            "content_type": "application/pdf", "size_bytes": 10, "sha256": "a" * 64,
        }, org)
        old_attempt = job.selected_attempt_id
        event = EVENT_ADAPTER.validate_python({
            "schema_version": "1", "job_id": job.job_id, "attempt_id": old_attempt,
            "event_id": "terminal", "status": "failed", "error": {
                "code": "PREPARATION_FAILED", "message": "Document preparation failed.", "retryable": retryable,
            },
        })
        from app.services.cloudflare_coordinator import claim_preparation, checkpoint_terminal_event
        grant = claim_preparation(db_session, job.job_id, old_attempt)
        checkpoint_terminal_event(db_session, job.job_id, old_attempt, grant["checkpoint_token"], event.model_dump_json().encode())
        workflow_service.ingest_event(db_session, event)
        return client, job, old_attempt
    return create


@pytest.mark.parametrize("retryable", [True, False])
def test_preparation_failure_status_supports_a_new_attempt(failed_job, retryable):
    client, job, old_attempt = failed_job(retryable)
    status = client.get(f"/api/documents/status/{job.job_id}")
    assert status.status_code == 200, status.text
    assert status.json()["error_code"] == "PREPARATION_FAILED"
    assert status.json()["can_retry"] is retryable
    retry = client.post(f"/api/documents/{job.job_id}/retry")
    if not retryable:
        assert retry.status_code == 409, retry.text
        return
    assert retry.status_code == 200, retry.text
    assert retry.json()["status"] == "queued"
    assert job.selected_attempt_id != old_attempt
    status = client.get(f"/api/documents/status/{job.job_id}").json()
    assert status["error_code"] is None
    assert status["can_retry"] is False
    assert client.post(f"/api/documents/{job.job_id}/retry").status_code == 409


def test_legacy_failure_status_cannot_retry(client, db_session):
    from app.models.extraction_job import ExtractionJob

    job = ExtractionJob(job_id=uuid4().hex, status="failed", error="legacy failure", message="Extraction failed")
    db_session.add(job)
    db_session.flush()
    response = client.get(f"/api/documents/status/{job.job_id}")
    assert response.status_code == 200, response.text
    assert response.json()["can_retry"] is False


@pytest.mark.parametrize("limit", [
    "EXTRACTION_MONTHLY_LIMIT", "EXTRACTION_MONTHLY_ATTEMPT_LIMIT",
    "EXTRACTION_FREE_LIMIT", "EXTRACTION_GLOBAL_TRIAL_MONTHLY_LIMIT",
    "EXTRACTION_GLOBAL_TRIAL_CALL_MONTHLY_LIMIT", "EXTRACTION_ATTEMPTS_PER_MINUTE",
])
def test_retry_quota_denials_are_read_only_and_shared_with_post(failed_job, db_session, monkeypatch, limit):
    from sqlalchemy import text
    from app.services.extraction_quota import reserve_extraction, settle_extraction
    client, job, old_attempt = failed_job()
    reserve_extraction(db_session, job.org_id, old_attempt, has_customer_key=False, global_trial_limit=100)
    settle_extraction(db_session, job.org_id, old_attempt, success=False)
    db_session.commit()
    monkeypatch.setattr(settings, "EXTRACTION_QUOTA_ENABLED", True)
    monkeypatch.setattr(settings, "EXTRACTION_GLOBAL_TRIAL_MONTHLY_LIMIT", 100)
    monkeypatch.setattr(settings, "EXTRACTION_GLOBAL_TRIAL_CALL_MONTHLY_LIMIT", 100)
    monkeypatch.setattr(settings, limit, 0)

    def snapshot():
        return tuple(db_session.execute(text(f"SELECT row_to_json(t)::text FROM {table} t")).all()
                     for table in ("extraction_quota_global", "extraction_quota_org", "extraction_rate_org", "extraction_quota_reservations"))

    before = snapshot()
    for _ in range(2):
        response = client.get(f"/api/documents/status/{job.job_id}")
        assert response.status_code == 200, response.text
        assert response.json()["can_retry"] is False
    retry = client.post(f"/api/documents/{job.job_id}/retry")
    assert retry.status_code == 429, retry.text
    assert job.selected_attempt_id == old_attempt
    assert snapshot() == before
