from datetime import datetime, timedelta, timezone

import pytest

from app.services.orphan_reconciliation import inventory_candidates
from app.services.storage_service import tenant_prefix


def test_inventory_reports_only_old_unreferenced_originals():
    now = datetime(2026, 11, 6, tzinfo=timezone.utc)
    prefix = tenant_prefix("org-a")
    old = prefix + "11111111-1111-4111-8111-111111111111/original.pdf"
    referenced = prefix + "22222222-2222-4222-8222-222222222222/original.pdf"
    fresh = prefix + "33333333-3333-4333-8333-333333333333/original.pdf"

    class Storage:
        def list_originals(self):
            return iter([(old, now - timedelta(days=2)), (referenced, now - timedelta(days=2)), (fresh, now)])

        def delete(self, _key):
            pytest.fail("Reporting must never delete an object")

    candidates = list(inventory_candidates(Storage(), lambda key: key == referenced, now=now))
    assert candidates == [(old, now - timedelta(days=2))]


def test_inventory_stops_if_reference_check_fails():
    key = tenant_prefix("org") + "11111111-1111-4111-8111-111111111111/original.pdf"

    class Storage:
        def list_originals(self):
            return iter([(key, datetime(2020, 1, 1, tzinfo=timezone.utc))])

    def unavailable(_key):
        raise RuntimeError("database unavailable")

    with pytest.raises(RuntimeError):
        list(inventory_candidates(Storage(), unavailable))


def test_dedicated_auditor_checks_references_without_reading_tenant_rows(monkeypatch):
    from pathlib import Path
    import runpy
    import sys
    from uuid import uuid4
    import psycopg
    from psycopg import sql
    from app.core.config import settings
    from conftest import TEST_DATABASE_URL

    role = "reink_audit_" + uuid4().hex[:16]
    job = uuid4().hex
    key = tenant_prefix("other-tenant") + "11111111-1111-4111-8111-111111111111/original.pdf"
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as owner:
        owner.execute(sql.SQL("CREATE ROLE {}").format(sql.Identifier(role)))
        try:
            monkeypatch.setattr(settings, "DATABASE_URL", TEST_DATABASE_URL)
            monkeypatch.setattr(sys, "argv", ["provision_orphan_auditor.py", role])
            runpy.run_path(str(Path(__file__).resolve().parents[2] / "deploy/storage/provision_orphan_auditor.py"), run_name="__main__")
            assert owner.execute("SELECT has_function_privilege(%s, 'public.reink_storage_key_referenced(text)', 'EXECUTE')", (role,)).fetchone()[0]
            assert not owner.execute("SELECT has_any_column_privilege(%s, 'public.extraction_jobs', 'SELECT')", (role,)).fetchone()[0]
            with owner.transaction():
                owner.execute("INSERT INTO extraction_jobs(job_id,org_id,status,storage_key) VALUES (%s,'other-tenant','queued',%s)", (job, key))
                pending = key.replace("11111111-1111-4111-8111-111111111111", "33333333-3333-4333-8333-333333333333")
                owner.execute("INSERT INTO upload_intents(job_id,org_id,storage_key,status,lease_deadline) VALUES (%s,'other-tenant',%s,'uploading',clock_timestamp() - interval '1 hour')", ("intent-" + job, pending))
                owner.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(role)))
                assert owner.execute("SELECT public.reink_storage_key_referenced(%s)", (key,)).fetchone()[0] is True
                # Expiry alone never unprotects an in-flight upload.
                assert owner.execute("SELECT public.reink_storage_key_referenced(%s)", (pending,)).fetchone()[0] is True
                unused = key.replace("11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222")
                assert owner.execute("SELECT public.reink_storage_key_referenced(%s)", (unused,)).fetchone()[0] is False
                owner.execute("RESET ROLE")
                owner.execute("UPDATE upload_intents SET status='abandoned' WHERE job_id=%s", ("intent-" + job,))
                owner.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(role)))
                assert owner.execute("SELECT public.reink_storage_key_referenced(%s)", (pending,)).fetchone()[0] is False
                owner.execute("RESET ROLE")
                owner.execute("DELETE FROM upload_intents WHERE job_id=%s", ("intent-" + job,))
                owner.execute("DELETE FROM extraction_jobs WHERE job_id=%s", (job,))
        finally:
            owner.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role)))
            owner.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))
