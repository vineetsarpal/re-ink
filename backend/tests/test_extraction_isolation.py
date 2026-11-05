"""
Extraction-job tenant isolation — uploaded documents, their parsed results, and
the source files they point at are scoped per organization, so one org can never
read or download another org's documents.
"""
from __future__ import annotations

import asyncio
from io import BytesIO
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy.orm import sessionmaker

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


def test_endpoint_hides_another_orgs_document(as_org) -> None:
    """Org B cannot read another org's job status, results, or source file."""
    org_a = as_org(ORG_A)
    seeded = org_a.post("/api/documents/mock-job", json={"job_id": "doc-A"})
    assert seeded.status_code == 200, seeded.text

    org_b = as_org(ORG_B)
    assert org_b.get("/api/documents/status/doc-A").status_code == 404
    assert org_b.get("/api/documents/results/doc-A").status_code == 404
    assert org_b.get("/api/documents/file/doc-A").status_code == 404


def test_background_task_persists_results_under_rls(restricted_engine, monkeypatch) -> None:
    """The extraction worker, given its job's org, writes results back under RLS.

    Without the org binding its own session cannot see the job (RLS) and the
    result update silently no-ops — the exact fail-closed trap this slice fixes.
    """
    import app.api.endpoints.documents as documents

    Session = sessionmaker(bind=restricted_engine, autoflush=False)
    monkeypatch.setattr(documents, "SessionLocal", Session)

    async def fake_submit(file_path, api_key=None):
        return {"metadata": {"job_id": "landing-xyz"}, "markdown": "doc"}

    monkeypatch.setattr(
        documents.landingai_service, "submit_document_for_extraction", fake_submit
    )
    monkeypatch.setattr(
        documents.landingai_service, "parse_extraction_results", lambda raw: {"ok": True}
    )

    org = "org_bgtask_probe"

    def _cleanup() -> None:
        s = Session()
        bind_session_to_org(s, org)
        s.query(ExtractionJob).filter_by(job_id="bg-1").delete()
        s.commit()
        s.close()

    _cleanup()  # this test commits real rows, so pre-clean any prior leftover
    try:
        seed = Session()
        bind_session_to_org(seed, org)
        seed.add(
            ExtractionJob(job_id="bg-1", status="processing", file_path="/tmp/x.pdf")
        )
        seed.commit()
        seed.close()

        asyncio.run(
            documents.process_document_extraction("/tmp/x.pdf", "bg-1", "key", org)
        )

        check = Session()
        bind_session_to_org(check, org)
        job = check.query(ExtractionJob).filter_by(job_id="bg-1").one()
        assert job.status == "completed"
        assert job.parsed_results == {"ok": True}
        check.close()
    finally:
        _cleanup()


def test_uploaded_file_is_partitioned_by_org(tmp_path, monkeypatch) -> None:
    """Uploads land under a per-org subdirectory of the upload dir."""
    from app.services.document_service import document_service

    monkeypatch.setattr(document_service, "upload_dir", tmp_path)
    upload = UploadFile(BytesIO(b"%PDF-1.4 minimal"), filename="doc.pdf")

    info = asyncio.run(
        document_service.save_uploaded_file(upload, org_id="org_files_probe")
    )

    saved = Path(info["file_path"])
    assert saved.parent.name == "org_files_probe"
    assert saved.exists()
