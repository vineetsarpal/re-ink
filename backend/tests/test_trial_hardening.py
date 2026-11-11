"""Admission before storage, terminal upload intents, function privileges."""
from conftest import seed_trial_quota
import base64
import importlib.util
import io
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from fastapi import HTTPException
from psycopg import sql
from pypdf import PdfWriter
from sqlalchemy import text

from app.core.config import settings
from conftest import RESTRICTED_ROLE, TEST_DATABASE_URL


class Store:
    def __init__(self):
        self.objects, self.puts = {}, 0

    def put(self, key, data, content_type):
        self.puts += 1
        self.objects[key] = data

    def get(self, key):
        return self.objects[key]

    def delete(self, key):
        self.objects.pop(key, None)


def _pdf():
    data = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.write(data)
    return data.getvalue()


@pytest.fixture()
def trial(as_org, db_session, monkeypatch):
    import app.services.private_document_service as documents
    from sqlalchemy.orm import Session
    from app.core.tenancy import bind_session_to_org, get_tenant_db
    from app.main import app

    store = Store()
    monkeypatch.setattr(documents, "storage_service", store)
    for name, value in {
        "CLOUDFLARE_TRIAL_ENABLED": True, "EXTRACTION_QUOTA_ENABLED": True,
        "EXTRACTION_GLOBAL_TRIAL_MONTHLY_LIMIT": 100, "EXTRACTION_GLOBAL_TRIAL_CALL_MONTHLY_LIMIT": 100,
        "LANDINGAI_TRIAL_API_KEY": "trial-key",
        "PROVIDER_CREDENTIAL_ENCRYPTION_KEY": base64.urlsafe_b64encode(b"a" * 32).decode(),
    }.items():
        monkeypatch.setattr(settings, name, value)
    org_id = "hardening-" + uuid4().hex
    monkeypatch.setattr(settings, "TRIAL_ALLOWED_ORGANIZATION_IDS", [org_id])
    client = as_org(org_id)
    seed_trial_quota(db_session, org_id)
    connection = db_session.connection()

    def scoped_request():
        # Request rollbacks must not discard the test transaction.
        with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
            bind_session_to_org(session, org_id)
            yield session

    app.dependency_overrides[get_tenant_db] = scoped_request
    assert client.post("/api/provider-credentials/landingai/acknowledgment").status_code == 200
    pdf = _pdf()

    def upload():
        return client.post("/api/documents/upload", files={"file": ("sample.pdf", pdf, "application/pdf")})

    return org_id, client, store, upload


def _intents(db_session, org_id):
    from app.core.tenancy import bind_session_to_org
    bind_session_to_org(db_session, org_id)
    return db_session.execute(text("SELECT status FROM upload_intents WHERE org_id = :org"), {"org": org_id}).scalars().all()


def test_over_quota_upload_is_rejected_before_storage_and_rate_limited(trial, db_session, monkeypatch):
    org_id, client, store, upload = trial
    monkeypatch.setattr(settings, "EXTRACTION_FREE_LIMIT", 0)
    monkeypatch.setattr(settings, "EXTRACTION_ATTEMPTS_PER_MINUTE", 2)
    for _ in range(2):
        response = upload()
        assert response.status_code == 429
        assert "exhausted" in response.json()["detail"]
    throttled = upload()
    assert throttled.status_code == 429
    assert "Too many" in throttled.json()["detail"]
    assert throttled.headers["Retry-After"] == "60"
    assert store.puts == 0
    assert _intents(db_session, org_id) == []


def test_reservation_race_after_store_marks_intent_terminal(trial, db_session, monkeypatch):
    import app.services.workflow_service as workflows
    org_id, _, store, upload = trial

    def lost_race(*args, **kwargs):
        raise HTTPException(429, "Monthly extraction limit reached")

    monkeypatch.setattr(workflows, "reserve_extraction", lost_race)
    assert upload().status_code == 429
    assert store.puts == 1 and not store.objects
    assert _intents(db_session, org_id) == ["deleted"]


def test_usage_is_a_plain_read(db_session):
    from app.core.tenancy import bind_session_to_org
    from app.services.extraction_quota import quota_usage

    org_id = "usage-read-" + uuid4().hex
    bind_session_to_org(db_session, org_id)
    statements = []
    connection = db_session.connection()
    from sqlalchemy import event

    def record(conn, cursor, statement, *args):
        statements.append(statement.upper())

    event.listen(connection, "before_cursor_execute", record)
    try:
        usage = quota_usage(db_session, org_id)
    finally:
        event.remove(connection, "before_cursor_execute", record)
    assert (usage.monthly_successes, usage.monthly_attempts, usage.pending, usage.free_successes, usage.free_pending) == (0, 0, 0, 0, 0)
    assert statements and not any("FOR UPDATE" in s or s.lstrip().startswith("INSERT") for s in statements)


def _definer_functions(conn):
    return [row[0] for row in conn.execute(
        "SELECT p.oid::regprocedure::text FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
        "WHERE n.nspname = 'public' AND p.prosecdef AND p.proname LIKE 'reink\\_%' ORDER BY 1").fetchall()]


def test_app_role_cannot_execute_definer_functions_and_search_path_is_pinned():
    with psycopg.connect(TEST_DATABASE_URL) as owner:
        functions = _definer_functions(owner)
        assert len(functions) >= 10
        for name in functions:
            allowed, config = owner.execute(
                "SELECT has_function_privilege(%s, %s::regprocedure, 'EXECUTE'), "
                "(SELECT proconfig FROM pg_proc WHERE oid = %s::regprocedure)", (RESTRICTED_ROLE, name, name)).fetchone()
            assert not allowed, name
            assert config == ["search_path=pg_catalog, pg_temp"], name


def test_migration_revokes_execute_granted_by_owner_default_privileges():
    path = next((Path(__file__).resolve().parents[1] / "alembic/versions").glob("0015_*.py"))
    spec = importlib.util.spec_from_file_location("migration_0015", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with psycopg.connect(TEST_DATABASE_URL) as owner:
        functions = _definer_functions(owner)
        for name in functions:
            owner.execute(sql.SQL("GRANT EXECUTE ON FUNCTION {} TO {}").format(sql.SQL(name), sql.Identifier(RESTRICTED_ROLE)))
        owner.execute(migration.revoke_app_execute_sql(RESTRICTED_ROLE))
        for name in functions:
            assert not owner.execute("SELECT has_function_privilege(%s, %s::regprocedure, 'EXECUTE')", (RESTRICTED_ROLE, name)).fetchone()[0], name
        owner.rollback()


def test_restricted_app_role_call_is_denied(restricted_engine):
    from sqlalchemy.exc import ProgrammingError
    with restricted_engine.connect() as conn:
        with pytest.raises(ProgrammingError, match="permission denied"):
            conn.execute(text("SELECT public.reink_cleanup_upload_first()"))


def test_reconciliation_lookups_are_indexed():
    with psycopg.connect(TEST_DATABASE_URL) as owner:
        defs = [row[0] for row in owner.execute(
            "SELECT indexdef FROM pg_indexes WHERE schemaname = 'public' "
            "AND tablename IN ('extraction_jobs', 'storage_cleanup', 'upload_intents')").fetchall()]
    assert any("ON public.extraction_jobs USING btree (storage_key)" in d for d in defs)
    assert any("ON public.storage_cleanup USING btree (storage_key)" in d for d in defs)
    assert any("ON public.upload_intents" in d and "WHERE" in d and "abandoned" in d for d in defs)


def test_migration_fails_if_app_role_keeps_execute_through_another_grant():
    path = next((Path(__file__).resolve().parents[1] / "alembic/versions").glob("0015_*.py"))
    spec = importlib.util.spec_from_file_location("migration_0015", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    holder = "reink_test_exec_holder_" + uuid4().hex[:8]
    with psycopg.connect(TEST_DATABASE_URL) as owner:
        name = _definer_functions(owner)[0]
        owner.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(holder)))
        owner.execute(sql.SQL("GRANT EXECUTE ON FUNCTION {} TO {}").format(sql.SQL(name), sql.Identifier(holder)))
        owner.execute(sql.SQL("GRANT {} TO {}").format(sql.Identifier(holder), sql.Identifier(RESTRICTED_ROLE)))
        with pytest.raises(psycopg.errors.RaiseException, match="still has access"):
            owner.execute(migration.revoke_app_execute_sql(RESTRICTED_ROLE))
        owner.rollback()
