import pytest
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4
from sqlalchemy import text
from sqlalchemy.orm import Session
from test_private_document_service import fake_storage
from app.models.organization_lifecycle import OrganizationLifecycle
from app.services.storage_service import tenant_prefix

from fastapi.testclient import TestClient

from app.main import app


def test_purge_requires_scheduler_credential(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, 'CLOUDFLARE_ENABLED', True)
    monkeypatch.setattr(settings, 'CLOUDFLARE_PURGE_TOKEN', 'p' * 32)
    response = TestClient(app).post('/api/maintenance/purge')
    assert response.status_code == 401
    for token in ['wrong', 'x' * 513]:
        assert TestClient(app).post('/api/maintenance/purge', headers={'Authorization': 'Bearer ' + token}).status_code == 401




@pytest.fixture
def purge_env(db_session, monkeypatch, fake_storage):
    from app.api.endpoints import purge_maintenance as route
    from app.core.config import settings
    monkeypatch.setattr(settings, 'CLOUDFLARE_ENABLED', True)
    monkeypatch.setattr(settings, 'CLOUDFLARE_PURGE_TOKEN', 'p' * 32)
    monkeypatch.setattr(settings, 'WORKOS_API_KEY', 'test-workos-key')
    monkeypatch.setattr(settings, 'WORKOS_CLIENT_ID', 'test-client')
    connection = db_session.connection()
    @contextmanager
    def factory():
        with Session(bind=connection, join_transaction_mode='create_savepoint') as session:
            yield session
    monkeypatch.setattr(route, 'maintenance_factory', lambda: factory)
    monkeypatch.setattr(fake_storage, 'list_objects', lambda org: [(key, datetime.now(timezone.utc))
        for key in list(fake_storage.objects) if key.startswith(tenant_prefix(org))], raising=False)
    monkeypatch.setattr(route, 'storage_service', fake_storage, raising=False)
    wos = MagicMock()
    monkeypatch.setattr(route, '_workos_client', lambda: wos, raising=False)
    org = 'purge-' + uuid4().hex
    row = OrganizationLifecycle(org_id=org, status='closing',
        closure_requested_at=datetime.now(timezone.utc) - timedelta(days=31),
        purge_after=datetime.now(timezone.utc) - timedelta(days=1), requested_by_hash='a' * 64)
    db_session.add(row)
    db_session.flush()
    def run():
        response = TestClient(app).post('/api/maintenance/purge', headers={'Authorization': 'Bearer ' + 'p' * 32})
        db_session.expire_all()
        return response
    return SimpleNamespace(org=org, row=row, db=db_session, store=fake_storage, wos=wos, run=run)


def test_due_organization_is_purged(purge_env):
    env = purge_env
    key = tenant_prefix(env.org) + str(uuid4()) + '/original.pdf'
    env.store.put(key, b'original', 'application/pdf')
    response = env.run()
    assert response.status_code == 200, response.text
    assert response.json()['processed'] == 1
    assert env.row.status == 'purged'
    assert not env.store.objects
    env.wos.organizations.delete_organization.assert_called_once_with(env.org)


@pytest.mark.parametrize('state', ['active', 'future'])
def test_purge_skips_cancelled_and_future_closures(purge_env, state):
    env = purge_env
    if state == 'active':
        env.row.status = 'active'
    else:
        env.row.purge_after = datetime.now(timezone.utc) + timedelta(days=1)
    env.db.flush()
    assert env.run().json()['processed'] == 0
    env.wos.organizations.delete_organization.assert_not_called()


def test_nonempty_storage_records_failure_without_deleting_rows(purge_env, monkeypatch):
    from app.core.tenancy import bind_session_to_org
    from app.models.party import Party
    env = purge_env
    bind_session_to_org(env.db, env.org)
    env.db.add(Party(org_id=env.org, name='Retain until storage verified'))
    env.db.flush()
    key = tenant_prefix(env.org) + str(uuid4()) + '/original.pdf'
    env.store.put(key, b'original', 'application/pdf')
    original_delete = env.store.delete
    monkeypatch.setattr(env.store, 'delete', lambda key: None)
    assert env.run().status_code == 200
    assert env.row.status == 'closing'
    assert env.row.purge_attempts == 1
    assert env.row.last_purge_error
    bind_session_to_org(env.db, env.org)
    assert env.db.query(Party).filter_by(org_id=env.org).count() == 1
    env.wos.organizations.delete_organization.assert_not_called()
    monkeypatch.setattr(env.store, 'delete', original_delete)
    assert env.run().status_code == 200
    assert env.row.status == 'purged'
    assert env.row.purge_attempts == 2
    assert env.row.last_purge_error is None


def test_tenant_table_coverage_and_ordering(purge_env):
    from app.purge_worker import DELETE_TABLES, RETAIN_TABLES, ORG_TABLES_SQL
    from app.core.tenancy import bind_session_to_org
    from app.models.party import Party
    from app.models.extraction_quota import OrganizationQuota, QuotaReservation
    from app.models.extraction_quota import TrialUser, TrialDomain
    from conftest import seed_trial_quota
    env = purge_env
    assert set(env.db.scalars(text(ORG_TABLES_SQL))) == set(DELETE_TABLES) | RETAIN_TABLES
    seed_trial_quota(env.db, env.org)
    env.db.add_all([Party(org_id=env.org, name='Purge me'),
        QuotaReservation(org_id=env.org, attempt_id='historical', funding='trial', status='failed'),
        TrialUser(user_hash=uuid4().hex, org_id=env.org), TrialDomain(domain=uuid4().hex + '.example', org_id=env.org)])
    env.db.flush()
    _seed_all_tenant_tables(env.db, env.org)
    for table in DELETE_TABLES:
        assert env.db.scalar(text(f'SELECT count(*) FROM {table} WHERE org_id=:org'), {'org': env.org}) > 0, table
    def delete_org(org_id):
        assert not env.store.objects
        with env.db.connection().begin_nested():
            bind_session_to_org(env.db, org_id)
            for table in DELETE_TABLES:
                assert env.db.scalar(text(f'SELECT count(*) FROM {table} WHERE org_id=:org'), {'org': org_id}) == 0, table
    env.wos.organizations.delete_organization.side_effect = delete_org
    assert env.run().status_code == 200
    assert env.row.status == 'purged'
    bind_session_to_org(env.db, env.org)
    assert env.db.get(OrganizationQuota, env.org) is not None
    assert env.db.get(QuotaReservation, (env.org, 'historical')) is not None
    assert env.db.query(TrialUser).filter_by(org_id=env.org).count() == 1
    assert env.db.query(TrialDomain).filter_by(org_id=env.org).count() == 1


def test_workos_failure_resumes_without_storage_or_data_work(purge_env, monkeypatch):
    env = purge_env
    env.wos.organizations.delete_organization.side_effect = [RuntimeError('secret must not persist'), None]
    assert env.run().status_code == 200
    assert env.row.purge_step == 'data_done'
    assert 'secret' not in env.row.last_purge_error
    monkeypatch.setattr(env.store, 'list_objects', lambda org: pytest.fail('Storage repeated'))
    assert env.run().status_code == 200
    assert env.row.status == 'purged'
    assert env.wos.organizations.delete_organization.call_count == 2


def test_data_failure_retries_without_repeating_verified_storage(purge_env, monkeypatch):
    from app.core.tenancy import bind_session_to_org
    env = purge_env
    bind_session_to_org(env.db, env.org)
    from sqlalchemy import event
    connection = env.db.connection()
    def reject_delete(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith('DELETE FROM public.parties'):
            raise RuntimeError('Injected database failure')
    event.listen(connection, 'before_cursor_execute', reject_delete)
    try:
        assert env.run().status_code == 200
        assert env.row.purge_step == 'storage_done'
        env.wos.organizations.delete_organization.assert_not_called()
    finally:
        event.remove(connection, 'before_cursor_execute', reject_delete)
    monkeypatch.setattr(env.store, 'list_objects', lambda org: pytest.fail('Storage repeated'))
    assert env.run().status_code == 200
    assert env.row.status == 'purged'


def test_final_state_failure_does_not_repeat_workos_deletion(purge_env):
    from sqlalchemy import event
    env = purge_env
    connection = env.db.connection()
    def reject_final(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith('UPDATE organization_lifecycle') and parameters.get('status') == 'purged':
            raise RuntimeError('Final database write failed')
    event.listen(connection, 'before_cursor_execute', reject_final)
    try:
        assert env.run().status_code == 200
        assert env.row.purge_step == 'workos_done'
        assert env.row.status == 'closing'
    finally:
        event.remove(connection, 'before_cursor_execute', reject_final)
    assert env.run().status_code == 200
    assert env.row.status == 'purged'
    env.wos.organizations.delete_organization.assert_called_once()


def test_cancel_rejected_after_purge_started(purge_env, client, monkeypatch):
    from app.core.auth import CurrentUser, get_current_user
    env = purge_env
    env.wos.organizations.delete_organization.side_effect = RuntimeError('temporarily unavailable')
    assert env.run().status_code == 200
    assert env.row.purge_step == 'data_done'
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user_id='admin', org_id=env.org, permissions=['organization:close'])
    assert client.post('/api/organization/cancel-closure').status_code == 409


def _seed_all_tenant_tables(db, org):
    statements = [
        "INSERT INTO contracts (org_id,contract_number,contract_name,effective_date,expiration_date) VALUES (:org,:org,'Purge treaty',CURRENT_DATE,CURRENT_DATE)",
        "INSERT INTO contract_parties (org_id,contract_id,party_id,role) SELECT c.org_id,c.id,p.id,'cedant' FROM contracts c,parties p WHERE c.org_id=:org AND p.org_id=:org",
        "INSERT INTO extraction_jobs (job_id,org_id,status) VALUES (:org,:org,'cancelled')",
        "INSERT INTO extraction_attempts (attempt_id,job_id,org_id,number,status,created_at,deadline_at) VALUES (:org,:org,:org,1,'cancelled',now(),now())",
        "INSERT INTO cloudflare_executions (attempt_id,org_id,token_digest) VALUES (:org,:org,'digest')",
        "INSERT INTO workflow_outbox (attempt_id,org_id,payload,next_delivery_at,delivery_count) VALUES (:org,:org,'{}',now(),0)",
        "INSERT INTO workflow_receipts (attempt_id,org_id,event_id,digest,acknowledgement) VALUES (:org,:org,'terminal','digest','{}')",
        "INSERT INTO storage_cleanup (cleanup_id,org_id,job_id,storage_key,next_attempt_at,attempts) VALUES (:org,:org,:org,'key',now(),0)",
        "INSERT INTO upload_intents (job_id,org_id,storage_key,status,lease_deadline) VALUES (:org,:org,:org,'abandoned',now())",
        "INSERT INTO provider_acknowledgments (org_id,provider,notice_version,acknowledged_by) VALUES (:org,'landingai','v1','admin')",
        "INSERT INTO provider_credentials (org_id,provider,ciphertext) VALUES (:org,'landingai',decode('00','hex'))",
        "INSERT INTO provisioning_intents (user_id,intent_id,org_id,state) VALUES (:org,:intent,:org,'completed')",
    ]
    for statement in statements:
        db.execute(text(statement), {'org': org, 'intent': str(uuid4())})


def test_dedicated_role_purges_with_rls_and_cannot_read_secrets(purge_env, monkeypatch):
    import os
    import subprocess
    import sys
    import psycopg
    from psycopg import sql
    from sqlalchemy import create_engine
    from sqlalchemy.engine import make_url
    from sqlalchemy.orm import sessionmaker
    from conftest import TEST_DATABASE_URL
    from app.api.endpoints import purge_maintenance as route
    from app.core.tenancy import bind_session_to_org

    role = 'purge_test_' + uuid4().hex[:16]
    org, other = uuid4().hex, uuid4().hex
    password = 'test-only-password'
    owner = create_engine(TEST_DATABASE_URL.replace('postgresql://', 'postgresql+psycopg://'))
    engine = None
    try:
        with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as connection:
            connection.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {}').format(sql.Identifier(role), sql.Literal(password)))
        result = subprocess.run([sys.executable, '../deploy/storage/provision_purge.py', role],
            env={**os.environ, 'DATABASE_URL': TEST_DATABASE_URL, 'CLOUDFLARE_ENABLED': 'false'}, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        with owner.begin() as connection:
            connection.execute(text("INSERT INTO organization_lifecycle (org_id,status,closure_requested_at,purge_after,requested_by_hash) VALUES (:org,'closing',now()-interval '31 days',now()-interval '1 day','hash')"), {'org': org})
            connection.execute(text("INSERT INTO parties (org_id,name) VALUES (:org,'Target'),(:other,'Survivor')"), {'org': org, 'other': other})
            _seed_all_tenant_tables(connection, org)
            assert not connection.scalar(text('SELECT rolbypassrls FROM pg_roles WHERE rolname=:role'), {'role': role})
            for table in ('extraction_quota_org', 'trial_users', 'trial_domains'):
                assert not connection.scalar(text("SELECT has_table_privilege(:role,:table,'DELETE')"), {'role': role, 'table': table})
            assert not connection.scalar(text("SELECT has_column_privilege(:role,'provider_credentials','ciphertext','SELECT')"), {'role': role})
        url = make_url(TEST_DATABASE_URL).set(drivername='postgresql+psycopg', username=role, password=password)
        engine = create_engine(url)
        with Session(engine) as db:
            bind_session_to_org(db, org)
            assert db.execute(text('DELETE FROM parties WHERE org_id=:other'), {'other': other}).rowcount == 0
            db.rollback()
        monkeypatch.setattr(route, 'maintenance_factory', lambda: sessionmaker(engine, autoflush=False))
        assert purge_env.run().status_code == 200
        with owner.connect() as connection:
            assert connection.scalar(text('SELECT status FROM organization_lifecycle WHERE org_id=:org'), {'org': org}) == 'purged'
            assert connection.scalar(text('SELECT count(*) FROM parties WHERE org_id=:org'), {'org': other}) == 1
    finally:
        if engine:
            engine.dispose()
        with owner.begin() as connection:
            from app.purge_worker import DELETE_TABLES
            for table in DELETE_TABLES:
                connection.execute(text(f'DELETE FROM {table} WHERE org_id IN (:org,:other)'), {'org': org, 'other': other})
            connection.execute(text('DELETE FROM organization_lifecycle WHERE org_id=:org'), {'org': org})
        owner.dispose()
        with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as connection:
            connection.execute(sql.SQL('DROP OWNED BY {}').format(sql.Identifier(role)))
            connection.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(role)))
