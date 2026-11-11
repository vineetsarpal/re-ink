"""Tenant-safe physical cleanup of revoked originals."""
from pathlib import Path
import runpy
import sys
from unittest.mock import Mock
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import settings
from app.services.storage_service import tenant_prefix
from conftest import TEST_DATABASE_URL


def test_cleanup_scheduler_requires_auth_and_limits_work(monkeypatch):
    from app.api.endpoints import cleanup_maintenance

    app = FastAPI()
    app.include_router(cleanup_maintenance.router)
    app.dependency_overrides[cleanup_maintenance.maintenance_token] = lambda: "x" * 40
    clean = Mock(return_value=True)
    monkeypatch.setattr(cleanup_maintenance, "cleanup_next", clean)
    monkeypatch.setattr(cleanup_maintenance, "upload_first", lambda factory: False)
    monkeypatch.setattr(cleanup_maintenance, "maintenance_factory", lambda: object())
    client = TestClient(app)
    assert client.post("/maintenance/cleanup").status_code == 401
    assert client.post("/maintenance/cleanup", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert clean.call_count == 0
    response = client.post("/maintenance/cleanup", headers={"Authorization": "Bearer " + "x" * 40})
    assert response.status_code == 200
    assert response.json() == {"processed": 1}
    assert clean.call_count == 1


@pytest.mark.parametrize("scenario", ["live_job", "mismatched_key"])
def test_cleanup_scheduler_preserves_unsafe_original(monkeypatch, scenario):
    from app.api.endpoints import cleanup_maintenance

    role = "reink_cleanup_" + uuid4().hex[:16]
    org, job, cleanup = "cleanup-live-" + uuid4().hex, uuid4().hex, uuid4().hex
    key = tenant_prefix(org) + str(uuid4()) + "/original.pdf"
    root = Path(__file__).resolve().parents[2]
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as owner:
        owner.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD 'disposable-test-only'").format(sql.Identifier(role)))
        try:
            monkeypatch.setattr(settings, "DATABASE_URL", TEST_DATABASE_URL)
            monkeypatch.setattr(sys, "argv", ["provision_cleanup.py", role])
            runpy.run_path(str(root / "deploy/storage/provision_cleanup.py"))
            job_key = key if scenario == "live_job" else tenant_prefix(org) + str(uuid4()) + "/original.pdf"
            deleted_at = None if scenario == "live_job" else "2020-01-01T00:00:00+00:00"
            owner.execute("INSERT INTO extraction_jobs(job_id,org_id,status,storage_key,deleted_at) VALUES (%s,%s,'completed',%s,%s)", (job, org, job_key, deleted_at))
            owner.execute("INSERT INTO storage_cleanup(cleanup_id,org_id,storage_key,job_id,next_attempt_at,attempts) VALUES (%s,%s,%s,%s,TIMESTAMPTZ '1900-01-01 00:00:00+00',0)", (cleanup, org, key, job))
            url = make_url(TEST_DATABASE_URL).set(drivername="postgresql+psycopg", username=role, password="disposable-test-only").render_as_string(hide_password=False)
            engine = create_engine(url)
            try:
                storage = Mock()
                app = FastAPI()
                app.include_router(cleanup_maintenance.router)
                app.dependency_overrides[cleanup_maintenance.maintenance_token] = lambda: "x" * 40
                monkeypatch.setattr(cleanup_maintenance, "maintenance_factory", lambda: sessionmaker(bind=engine, autoflush=False))
                monkeypatch.setattr(cleanup_maintenance, "storage_service", storage)
                response = TestClient(app).post("/maintenance/cleanup", headers={"Authorization": "Bearer " + "x" * 40})
                assert response.status_code == 200, response.text
                storage.delete.assert_not_called()
                assert owner.execute("SELECT 1 FROM extraction_jobs WHERE job_id=%s", (job,)).fetchone()
            finally:
                engine.dispose()
        finally:
            owner.execute("DELETE FROM storage_cleanup WHERE cleanup_id=%s", (cleanup,))
            owner.execute("DELETE FROM extraction_jobs WHERE job_id=%s", (job,))
            owner.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role)))
            owner.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))


def test_cleanup_removes_originals_across_tenants_and_retries_failures(monkeypatch):
    from app.cleanup_worker import cleanup_next

    role = "reink_cleanup_" + uuid4().hex[:16]
    ids = [(uuid4().hex, uuid4().hex, "cleanup-" + uuid4().hex) for _ in range(2)]
    root = Path(__file__).resolve().parents[2]
    keys = [tenant_prefix(org) + str(uuid4()) + "/original.pdf" for _, _, org in ids]
    poison_job, poison_cleanup, poison_org = uuid4().hex, uuid4().hex, "cleanup-poison-" + uuid4().hex
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as owner:
        owner.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD 'disposable-test-only'").format(sql.Identifier(role)))
        try:
            monkeypatch.setattr(settings, "DATABASE_URL", TEST_DATABASE_URL)
            monkeypatch.setattr(sys, "argv", ["provision_cleanup.py", role])
            runpy.run_path(str(root / "deploy/storage/provision_cleanup.py"))
            assert not owner.execute("SELECT has_table_privilege(%s, 'public.extraction_jobs', 'DELETE')", (role,)).fetchone()[0]
            assert not owner.execute("SELECT has_column_privilege(%s, 'public.extraction_jobs', 'parsed_results', 'SELECT')", (role,)).fetchone()[0]
            assert not owner.execute("SELECT has_column_privilege(%s, 'public.extraction_quota_reservations', 'credential_snapshot', 'SELECT')", (role,)).fetchone()[0]
            for (job, cleanup, org), key in zip(ids, keys):
                owner.execute("INSERT INTO extraction_jobs(job_id,org_id,status,storage_key,deleted_at) VALUES (%s,%s,'failed',%s,clock_timestamp())", (job, org, key))
                owner.execute("INSERT INTO storage_cleanup(cleanup_id,org_id,storage_key,job_id,next_attempt_at,attempts) VALUES (%s,%s,%s,%s,TIMESTAMPTZ '1900-01-01 00:00:00+00',0)", (cleanup, org, key, job))
            # A corrupted cleanup record must not delete another tenant's key.
            owner.execute("INSERT INTO extraction_jobs(job_id,org_id,status,deleted_at) VALUES (%s,%s,'failed',clock_timestamp())", (poison_job, poison_org))
            owner.execute("INSERT INTO storage_cleanup(cleanup_id,org_id,storage_key,job_id,next_attempt_at,attempts) VALUES (%s,%s,%s,%s,TIMESTAMPTZ '1800-01-01 00:00:00+00',0)", (poison_cleanup, poison_org, keys[0], poison_job))
            url = make_url(TEST_DATABASE_URL).set(drivername="postgresql+psycopg", username=role, password="disposable-test-only").render_as_string(hide_password=False)
            engine = create_engine(url)
            try:
                factory = sessionmaker(bind=engine, autoflush=False)
                storage = Mock()
                storage.delete.side_effect = [Exception("transient"), None, None]
                assert cleanup_next(factory, storage) is True
                storage.delete.assert_not_called()
                assert cleanup_next(factory, storage) is True
                assert owner.execute("SELECT count(*) FROM storage_cleanup WHERE cleanup_id = ANY(%s)", ([item[1] for item in ids],)).fetchone()[0] == 2
                assert cleanup_next(factory, storage) is True
                owner.execute("UPDATE storage_cleanup SET next_attempt_at=TIMESTAMPTZ '1900-01-01 00:00:00+00' WHERE cleanup_id=ANY(%s)", ([item[1] for item in ids],))
                assert cleanup_next(factory, storage) is True
                assert owner.execute("SELECT count(*) FROM extraction_jobs WHERE job_id = ANY(%s)", ([item[0] for item in ids],)).fetchone()[0] == 0
                assert owner.execute("SELECT count(*) FROM storage_cleanup WHERE cleanup_id = ANY(%s)", ([item[1] for item in ids],)).fetchone()[0] == 0
                assert set(call.args[0] for call in storage.delete.call_args_list) == set(keys)
            finally:
                engine.dispose()
        finally:
            owner.execute("DELETE FROM storage_cleanup WHERE cleanup_id=%s", (poison_cleanup,))
            owner.execute("DELETE FROM extraction_jobs WHERE job_id=%s", (poison_job,))
            owner.execute("DELETE FROM storage_cleanup WHERE cleanup_id = ANY(%s)", ([item[1] for item in ids],))
            owner.execute("DELETE FROM extraction_jobs WHERE job_id = ANY(%s)", ([item[0] for item in ids],))
            owner.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role)))
            owner.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))
