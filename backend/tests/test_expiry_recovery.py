"""Maintenance recovers expired work without weakening tenant RLS."""
from conftest import seed_trial_quota
import base64
from datetime import datetime, timezone
from uuid import uuid4
from pathlib import Path
import runpy
import sys
from unittest.mock import MagicMock

import psycopg
import pytest
from psycopg import sql
from sqlalchemy import select
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.tenancy import bind_session_to_org
from app.models.extraction_quota import QuotaReservation
from app.models.workflow import ExtractionAttempt
from app.services.workflow_service import create_workflow_job
from conftest import RESTRICTED_ROLE, TEST_DATABASE_URL


def test_expiry_scheduler_requires_credential_and_bounds_work(monkeypatch):
    from app.api.endpoints import expiry_maintenance

    app = FastAPI()
    app.include_router(expiry_maintenance.router)
    app.dependency_overrides[expiry_maintenance.maintenance_token] = lambda: "x" * 40
    factory = MagicMock()
    monkeypatch.setattr(expiry_maintenance, "maintenance_factory", lambda: factory)
    expire = MagicMock(return_value=True)
    monkeypatch.setattr(expiry_maintenance, "expire_next", expire)
    client = TestClient(app)
    assert client.post("/maintenance/expiry").status_code == 401
    assert client.post("/maintenance/expiry", headers={"Authorization": "Bearer incorrect"}).status_code == 401
    assert expire.call_count == 0
    response = client.post("/maintenance/expiry", headers={"Authorization": "Bearer " + "x" * 40})
    assert response.status_code == 200
    assert response.json() == {"processed": 10}
    assert expire.call_count == 10


def test_expiry_role_has_only_required_access(monkeypatch):
    from app.expiry_worker import expire_next
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url
    from sqlalchemy.orm import Session

    role = "reink_expiry_" + uuid4().hex[:16]
    root = Path(__file__).resolve().parents[2]
    job_id, attempt_id, org = uuid4().hex, uuid4().hex, "expiry-role-" + uuid4().hex
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as owner:
        owner.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD 'disposable-test-only'").format(sql.Identifier(role)))
        try:
            monkeypatch.setattr(settings, "DATABASE_URL", TEST_DATABASE_URL)
            monkeypatch.setattr(sys, "argv", ["provision_expiry.py", role])
            runpy.run_path(str(root / "deploy/storage/provision_expiry.py"))
            assert owner.execute("SELECT has_function_privilege(%s, 'public.reink_next_expired_extraction()', 'EXECUTE')", (role,)).fetchone()[0]
            assert not owner.execute("SELECT has_table_privilege(%s, 'public.provider_credentials', 'SELECT')", (role,)).fetchone()[0]
            assert not owner.execute("SELECT has_table_privilege(%s, 'public.contracts', 'UPDATE')", (role,)).fetchone()[0]
            assert not owner.execute("SELECT has_column_privilege(%s, 'public.extraction_jobs', 'parsed_results', 'SELECT')", (role,)).fetchone()[0]
            assert not owner.execute("SELECT has_column_privilege(%s, 'public.extraction_quota_reservations', 'credential_snapshot', 'SELECT')", (role,)).fetchone()[0]
            url = make_url(TEST_DATABASE_URL).set(drivername="postgresql+psycopg").render_as_string(hide_password=False)
            engine = create_engine(url)
            try:
                with engine.connect() as connection:
                    transaction = connection.begin()
                    try:
                        connection.execute(text("INSERT INTO extraction_jobs(job_id, org_id, status, selected_attempt_id) VALUES (:job,:org,'queued',:attempt)"), {"job": job_id, "org": org, "attempt": attempt_id})
                        connection.execute(text("INSERT INTO extraction_attempts(attempt_id,job_id,org_id,number,status,created_at,deadline_at) VALUES (:attempt,:job,:org,1,'queued',clock_timestamp(),TIMESTAMPTZ '1000-01-01 00:00:00+00')"), {"attempt": attempt_id, "job": job_id, "org": org})
                        connection.execute(text("INSERT INTO extraction_quota_org(org_id,month,monthly_successes,monthly_attempts,pending,free_successes,free_pending) VALUES (:org,date_trunc('month',now())::date,0,1,1,0,0)"), {"org": org})
                        connection.execute(text("INSERT INTO extraction_quota_reservations(org_id,attempt_id,funding,status,credential_snapshot) VALUES (:org,:attempt,'customer','pending',:ciphertext)"), {"org": org, "attempt": attempt_id, "ciphertext": b"encrypted-key"})
                        connection.exec_driver_sql('SET LOCAL ROLE "' + role + '"')
                        with Session(bind=connection) as db:
                            assert expire_next(db) is True
                            db.flush()
                            connection.exec_driver_sql("RESET ROLE")
                            assert connection.execute(text("SELECT status FROM extraction_jobs WHERE job_id=:job"), {"job": job_id}).scalar_one() == "timed_out"
                            result = connection.execute(text("SELECT status,credential_snapshot FROM extraction_quota_reservations WHERE org_id=:org AND attempt_id=:attempt"), {"org": org, "attempt": attempt_id}).one()
                            assert tuple(result) == ("failed", None)
                    finally:
                        transaction.rollback()
            finally:
                engine.dispose()
        finally:
            owner.execute("DELETE FROM extraction_quota_reservations WHERE org_id=%s", (org,))
            owner.execute("DELETE FROM extraction_quota_org WHERE org_id=%s", (org,))
            owner.execute("DELETE FROM extraction_attempts WHERE attempt_id=%s", (attempt_id,))
            owner.execute("DELETE FROM extraction_jobs WHERE job_id=%s", (job_id,))
            owner.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role)))
            owner.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))


def test_expiry_provision_rejects_preexisting_column_grant(monkeypatch):
    role = "reink_expiry_" + uuid4().hex[:16]
    root = Path(__file__).resolve().parents[2]
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as owner:
        owner.execute(sql.SQL("CREATE ROLE {}").format(sql.Identifier(role)))
        try:
            owner.execute(sql.SQL("GRANT SELECT (parsed_results) ON public.extraction_jobs TO {}").format(sql.Identifier(role)))
            monkeypatch.setattr(settings, "DATABASE_URL", TEST_DATABASE_URL)
            monkeypatch.setattr(sys, "argv", ["provision_expiry.py", role])
            with pytest.raises(SystemExit, match="existing.*privileges"):
                runpy.run_path(str(root / "deploy/storage/provision_expiry.py"))
        finally:
            owner.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role)))
            owner.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))


def test_expiry_maintenance_discovers_tenants_and_releases_reservations(db_session, monkeypatch):
    from app.expiry_worker import expire_next

    monkeypatch.setattr(settings, "EXTRACTION_QUOTA_ENABLED", True)
    monkeypatch.setattr(settings, "EXTRACTION_GLOBAL_TRIAL_MONTHLY_LIMIT", 100)
    monkeypatch.setattr(settings, "EXTRACTION_GLOBAL_TRIAL_CALL_MONTHLY_LIMIT", 100)
    monkeypatch.setattr(settings, "LANDINGAI_TRIAL_API_KEY", "trial-key")
    monkeypatch.setattr(settings, "PROVIDER_CREDENTIAL_ENCRYPTION_KEY", base64.urlsafe_b64encode(b"a" * 32).decode())
    orgs = ["expiry-a-" + uuid4().hex, "expiry-b-" + uuid4().hex]
    attempts = []
    for org in orgs:
        bind_session_to_org(db_session, org)
        seed_trial_quota(db_session, org)
        job = create_workflow_job(db_session, {"job_id": uuid4().hex, "filename": "test.pdf", "storage_key": "key", "content_type": "application/pdf", "size_bytes": 5, "sha256": "a" * 64}, org)
        attempt = db_session.get(ExtractionAttempt, job.selected_attempt_id)
        attempt.deadline_at = datetime(1000, 1, 1, tzinfo=timezone.utc)
        attempts.append(attempt.attempt_id)
        db_session.flush()

    assert not db_session.scalar(select(ExtractionAttempt).where(ExtractionAttempt.org_id == orgs[0]))
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as admin:
        admin.execute(sql.SQL("GRANT EXECUTE ON FUNCTION public.reink_next_expired_extraction() TO {}").format(sql.Identifier(RESTRICTED_ROLE)))
        try:
            for _ in range(100):
                assert expire_next(db_session) is True
                statuses = []
                for org, attempt_id in zip(orgs, attempts):
                    bind_session_to_org(db_session, org)
                    seed_trial_quota(db_session, org)
                    statuses.append(db_session.scalar(select(ExtractionAttempt.status).where(ExtractionAttempt.attempt_id == attempt_id)))
                if statuses == ["timed_out", "timed_out"]:
                    break
            else:
                pytest.fail("Test jobs were not reached within the bounded sweep")
            for org, attempt_id in zip(orgs, attempts):
                bind_session_to_org(db_session, org)
                seed_trial_quota(db_session, org)
                assert db_session.get(ExtractionAttempt, attempt_id).status == "timed_out"
                reservation = db_session.get(QuotaReservation, (org, attempt_id))
                assert reservation.status == "failed"
                assert reservation.credential_snapshot is None
        finally:
            admin.execute(sql.SQL("REVOKE EXECUTE ON FUNCTION public.reink_next_expired_extraction() FROM {}").format(sql.Identifier(RESTRICTED_ROLE)))
