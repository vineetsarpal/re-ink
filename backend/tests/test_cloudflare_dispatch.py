"""Cloudflare queue publishing over the real tenant-scoped outbox."""
from datetime import datetime, timezone
import uuid
import runpy
import sys
from pathlib import Path

import httpx
import psycopg
from psycopg import sql
import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import sessionmaker

from app.models.workflow import WorkflowOutbox
from app.services.dispatch_capability import verify_capability
from app.services.workflow_service import create_workflow_job
from app.core.config import settings
from conftest import TEST_DATABASE_URL


def test_queue_publish_is_tenant_scoped_and_does_not_start_extraction(restricted_engine, request):
    from app.services.cloudflare_dispatch import CloudflareQueueConfig, dispatch_cloudflare_once

    org = 'producer-' + uuid.uuid4().hex
    factory = sessionmaker(bind=restricted_engine, autoflush=False, expire_on_commit=False)
    with factory() as db:
        @event.listens_for(db, 'after_begin')
        def bind(session, transaction, connection):
            connection.exec_driver_sql("SELECT set_config('app.current_org', %s, true)", (org,))
        job = create_workflow_job(db, {'job_id': uuid.uuid4().hex, 'filename': 'a.pdf', 'storage_key': 'test', 'content_type': 'application/pdf', 'size_bytes': 4, 'sha256': 'a' * 64}, org)
        job_id, attempt_id = job.job_id, job.selected_attempt_id
        db.commit()

    def cleanup():
        with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as owner:
            owner.execute('DELETE FROM workflow_outbox WHERE attempt_id=%s', (attempt_id,))
            owner.execute('DELETE FROM extraction_attempts WHERE attempt_id=%s', (attempt_id,))
            owner.execute('DELETE FROM extraction_jobs WHERE job_id=%s', (job_id,))
    request.addfinalizer(cleanup)

    sent = []
    def handle(request):
        import json
        sent.append((request, json.loads(request.content)))
        return httpx.Response(200, json={'success': True, 'result': {}})

    config = CloudflareQueueConfig(account_id='a' * 32, queue_id='b' * 32, api_token='test-token', capability_key=b'k' * 32, queue_timeout=600, processing_timeout=600)
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        assert dispatch_cloudflare_once(factory, org, config, client)

    request, body = sent[0]
    assert str(request.url) == f'https://api.cloudflare.com/client/v4/accounts/{"a" * 32}/queues/{"b" * 32}/messages'
    message = body['body']
    assert body['content_type'] == 'json'
    assert set(message) == {'schema_version', 'operation', 'job_id', 'attempt_id', 'capability'}
    assert verify_capability(message['capability'], [b'k' * 32], job_id, attempt_id) == org
    with factory() as db:
        from app.core.tenancy import bind_session_to_org
        from app.models.extraction_job import ExtractionJob
        bind_session_to_org(db, org)
        assert db.get(ExtractionJob, job_id).status == 'queued'
        assert db.get(WorkflowOutbox, attempt_id).acknowledged_at is not None


@pytest.mark.parametrize('accepted', [True, False])
def test_dispatch_role_cannot_read_customer_data_or_secrets(monkeypatch, restricted_engine, accepted):
    """The global dispatch identity only reads routing data, not customer payloads."""
    from sqlalchemy.engine import make_url
    role = 'reink_dispatch_' + uuid.uuid4().hex[:12]
    org = 'dispatch-scope-' + uuid.uuid4().hex
    job_id = uuid.uuid4().hex
    root = Path(__file__).resolve().parents[2]
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as owner:
        owner.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD 'disposable-test-only'").format(sql.Identifier(role)))
        try:
            with sessionmaker(bind=restricted_engine, autoflush=False)() as db:
                from app.core.tenancy import bind_session_to_org
                bind_session_to_org(db, org)
                job = create_workflow_job(db, {'job_id': job_id, 'filename': 'a.pdf', 'storage_key': 'test', 'content_type': 'application/pdf', 'size_bytes': 4, 'sha256': 'a' * 64}, org)
                attempt_id = job.selected_attempt_id
                db.commit()
            monkeypatch.setattr(settings, 'DATABASE_URL', TEST_DATABASE_URL)
            monkeypatch.setattr(sys, 'argv', ['provision_cloudflare_dispatch.py', role])
            runpy.run_path(str(root / 'deploy/storage/provision_cloudflare_dispatch.py'))
            role_url = make_url(TEST_DATABASE_URL).set(username=role, password='disposable-test-only').render_as_string(hide_password=False)
            with psycopg.connect(role_url, autocommit=True) as worker:
                for query in ('SELECT parsed_results FROM extraction_jobs LIMIT 1',
                              'SELECT credential_snapshot FROM extraction_quota_reservations LIMIT 1'):
                    with pytest.raises(psycopg.errors.InsufficientPrivilege):
                        worker.execute(query)
            from sqlalchemy import create_engine
            from app.services.cloudflare_dispatch import CloudflareQueueConfig, dispatch_cloudflare_once
            engine = create_engine(role_url.replace('postgresql://', 'postgresql+psycopg://', 1))
            try:
                factory = sessionmaker(bind=engine, autoflush=False)
                config = CloudflareQueueConfig('a' * 32, 'b' * 32, 'test-token', b'k' * 32, 600, 600)
                status = 200 if accepted else 503
                with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(status, json={'success': accepted}))) as client:
                    assert dispatch_cloudflare_once(factory, org, config, client)
                row = owner.execute('SELECT acknowledged_at, lease_token, last_error FROM workflow_outbox WHERE attempt_id=%s', (attempt_id,)).fetchone()
                assert (row[0] is not None) is accepted
                assert row[1] is None
                assert row[2] == (None if accepted else 'DELIVERY_RETRY')
            finally:
                engine.dispose()
        finally:
            owner.execute('DELETE FROM workflow_outbox WHERE attempt_id IN (SELECT attempt_id FROM extraction_attempts WHERE job_id=%s)', (job_id,))
            owner.execute('DELETE FROM extraction_attempts WHERE job_id=%s', (job_id,))
            owner.execute('DELETE FROM extraction_jobs WHERE job_id=%s', (job_id,))
            owner.execute(sql.SQL('DROP OWNED BY {}').format(sql.Identifier(role)))
            owner.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(role)))


def test_dispatch_provision_rejects_existing_column_grants(monkeypatch):
    role = 'reink_dispatch_' + uuid.uuid4().hex[:12]
    root = Path(__file__).resolve().parents[2]
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as owner:
        owner.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD 'disposable-test-only'").format(sql.Identifier(role)))
        try:
            owner.execute(sql.SQL('GRANT SELECT (parsed_results) ON extraction_jobs TO {}').format(sql.Identifier(role)))
            monkeypatch.setattr(settings, 'DATABASE_URL', TEST_DATABASE_URL)
            monkeypatch.setattr(sys, 'argv', ['provision_cloudflare_dispatch.py', role])
            with pytest.raises(SystemExit, match='column privileges'):
                runpy.run_path(str(root / 'deploy/storage/provision_cloudflare_dispatch.py'))
        finally:
            owner.execute(sql.SQL('DROP OWNED BY {}').format(sql.Identifier(role)))
            owner.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(role)))
