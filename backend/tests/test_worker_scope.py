"""Verify operator provisioning and access checks with a dedicated disposable role."""
from pathlib import Path
import runpy
import sys
import uuid

import psycopg
from psycopg import sql

from app.core.config import settings
from conftest import TEST_DATABASE_URL


def test_worker_literal_tenant_fence_and_no_approval_writes(monkeypatch):
    root = Path(__file__).resolve().parents[2]
    role = "reink_worker_" + uuid.uuid4().hex[:16]
    org, other_org = "scope-" + uuid.uuid4().hex, "other-" + uuid.uuid4().hex
    own_job, other_job = uuid.uuid4().hex, uuid.uuid4().hex
    tables = ("extraction_jobs", "extraction_attempts", "workflow_outbox", "workflow_receipts", "storage_cleanup")
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as owner:
        owner.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD 'disposable-test-only'").format(sql.Identifier(role)))
        try:
            owner.execute("INSERT INTO extraction_jobs(job_id,org_id,status) VALUES (%s,%s,'queued'),(%s,%s,'queued')", (own_job, org, other_job, other_org))
            monkeypatch.setattr(settings, "DATABASE_URL", TEST_DATABASE_URL)
            monkeypatch.setattr(settings, "WORKFLOW_CUSTOMER_ORG_ID", org)
            monkeypatch.setattr(sys, "argv", ["provision_worker.py", role])
            runpy.run_path(str(root / "deploy/storage/provision_worker.py"))
            check = runpy.run_path(str(root / "deploy/storage/check_worker_access.py"))["check"]
            from sqlalchemy.engine import make_url
            worker_url = make_url(TEST_DATABASE_URL).set(username=role, password="disposable-test-only").render_as_string(hide_password=False)
            check(worker_url, org, other_org, local_test=True)
            with psycopg.connect(worker_url) as worker:
                worker.execute("SELECT set_config('app.current_org',%s,true)", (org,))
                assert worker.execute("SELECT job_id FROM extraction_jobs").fetchall() == [(own_job,)]
                for table in ("contracts", "parties"):
                    try:
                        with worker.transaction():
                            worker.execute(sql.SQL("DELETE FROM {}").format(sql.Identifier(table)))
                    except psycopg.errors.InsufficientPrivilege:
                        pass
                    else:
                        raise AssertionError("Worker can write approval records")
                worker.rollback()
        finally:
            owner.execute("DELETE FROM extraction_jobs WHERE job_id IN (%s,%s)", (own_job, other_job))
            for table in tables:
                owner.execute(sql.SQL("DROP POLICY IF EXISTS {} ON {}").format(sql.Identifier("worker_scope_" + role), sql.Identifier(table)))
            owner.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role)))
            owner.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))
