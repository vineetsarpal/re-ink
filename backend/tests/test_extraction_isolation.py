"""
Extraction-job tenant isolation — uploaded documents, their parsed results, and
the source files they point at are scoped per organization, so one org can never
read or download another org's documents.
"""
from __future__ import annotations

from app.core.tenancy import bind_session_to_org
from app.models.extraction_job import ExtractionJob

ORG_A = "org_aaaaaaaaaaaaaaaaaaaaaaaa"
ORG_B = "org_bbbbbbbbbbbbbbbbbbbbbbbb"


def test_extraction_job_is_invisible_to_another_org(db_session) -> None:
    bind_session_to_org(db_session, ORG_A)
    db_session.add(ExtractionJob(job_id="job-A", status="completed", filename="a.pdf"))
    db_session.flush()

    bind_session_to_org(db_session, ORG_B)
    assert db_session.query(ExtractionJob).filter_by(job_id="job-A").count() == 0


def test_endpoint_hides_another_orgs_document(as_org, db_session) -> None:
    """Even workflow-shaped rows never disclose a different organization's data."""
    bind_session_to_org(db_session, ORG_A)
    db_session.add(ExtractionJob(job_id="doc-A", status="completed", filename="a.pdf",
                                 selected_attempt_id="attempt-A", parsed_results={}))
    db_session.flush()
    org_b = as_org(ORG_B)
    for path in ("status", "results", "file"):
        assert org_b.get(f"/api/documents/{path}/doc-A").status_code == 404


def test_legacy_rows_are_excluded_from_human_workflow_endpoints(as_org, db_session):
    bind_session_to_org(db_session, ORG_A)
    db_session.add(ExtractionJob(job_id="legacy-A", status="completed", filename="a.pdf",
                                 parsed_results={}))
    db_session.flush()
    client = as_org(ORG_A)
    for path in ("status", "results", "file"):
        assert client.get(f"/api/documents/{path}/legacy-A").status_code == 404
    assert client.post("/api/documents/legacy-A/retry").status_code in (404, 503)
    assert client.post("/api/documents/mock-job", json={"job_id": "new"}).status_code == 405
