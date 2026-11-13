"""Approval regressions exercised through the API against real PostgreSQL."""
import pytest
from datetime import datetime, timezone
from decimal import Decimal

from app.core.tenancy import bind_session_to_org
from app.models.extraction_job import ExtractionJob
from conftest import DEFAULT_TEST_ORG


def approval_payload():
    return {
        "contract": {
            "contract_number": "REVIEW-REGRESSION",
            "contract_name": "Approval regression",
            "effective_date": "2026-01-01",
            "expiration_date": "2026-12-31",
        },
        "parties": [],
    }


@pytest.mark.parametrize("field", [
    "premium_description", "limit_description",
    "retention_description", "commission_description",
])
def test_approval_preserves_long_financial_descriptions(client, field):
    payload = approval_payload()
    description = "Full financial terms from the source document. " * 20
    payload["contract"][field] = description

    response = client.post("/api/review/approve", json=payload)
    assert response.status_code == 200, response.text
    saved = client.get(f"/api/contracts/{response.json()['contract_id']}")
    assert saved.status_code == 200, saved.text
    assert saved.json()[field] == description


def test_approval_failure_does_not_expose_database_details(client, db_session, monkeypatch):
    def fail_commit():
        raise RuntimeError("SQL INSERT INTO contracts; confidential parameters")

    monkeypatch.setattr(db_session, "commit", fail_commit)
    response = client.post("/api/review/approve", json=approval_payload())

    assert response.status_code == 500
    assert response.json() == {
        "detail": "Unable to save the reviewed contract. Please try again."
    }


def seed_job(db_session, **overrides):
    values = dict(
        job_id="review-source", status="completed", filename="source.pdf",
        parsed_results={"contract_data": {}, "parties_data": [], "confidence_score": 0.91},
    )
    values.update(overrides)
    job = ExtractionJob(**values)
    db_session.add(job)
    db_session.flush()
    return job


@pytest.mark.parametrize("file_path", [None, "/uploads/source.pdf"])
def test_approval_copies_source_metadata_from_tenant_job(client, db_session, file_path):
    job = seed_job(db_session, file_path=file_path)
    payload = approval_payload()
    payload["job_id"] = job.job_id
    payload["contract"]["source_document_name"] = "untrusted-client-name.pdf"

    response = client.post("/api/review/approve", json=payload)
    assert response.status_code == 200, response.text
    saved = client.get(f"/api/contracts/{response.json()['contract_id']}").json()
    assert saved["source_document_name"] == "source.pdf"
    assert saved["source_document_path"] == file_path
    assert saved["extraction_job_id"] == job.job_id
    assert Decimal(saved["extraction_confidence"]) == Decimal("0.91")


@pytest.mark.parametrize("state", ["missing", "other_org", "deleted", "queued", "processing", "failed"])
def test_approval_rejects_unavailable_source_jobs(client, db_session, state):
    if state == "other_org":
        bind_session_to_org(db_session, "org_other_review")
        seed_job(db_session)
        bind_session_to_org(db_session, DEFAULT_TEST_ORG)
    elif state != "missing":
        seed_job(db_session, **(
            {"deleted_at": datetime.now(timezone.utc)} if state == "deleted"
            else {"status": state}
        ))
    payload = approval_payload()
    payload["job_id"] = "review-source"
    response = client.post("/api/review/approve", json=payload)
    assert response.status_code == (404 if state in {"missing", "other_org", "deleted"} else 409)
