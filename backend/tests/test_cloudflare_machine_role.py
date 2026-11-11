"""The provisioned machine role can run its job without reading stored results."""
import runpy
import base64
import sys
import uuid
from pathlib import Path

import psycopg
import pytest
from psycopg import sql
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.api.endpoints.cloudflare import router, CloudflareTransportSettings, transport_settings, session_factory
from app.core.config import settings
from app.core.tenancy import bind_session_to_org
from app.services.dispatch_capability import issue_capability
from app.services.workflow_service import create_workflow_job
from app.services.provider_credentials import encrypt_credential
from app.models.provider_credential import ProviderCredential
from conftest import TEST_DATABASE_URL


@pytest.mark.parametrize('with_quota', [False, True])
def test_machine_role_runs_checkpoint_delivery_without_reading_other_results(monkeypatch, restricted_engine, with_quota):
    role, org, job_id = ('reink_machine_' + uuid.uuid4().hex[:12], 'machine-' + uuid.uuid4().hex, uuid.uuid4().hex)
    key, token = b'k' * 32, 'm' * 32
    root = Path(__file__).resolve().parents[2]
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as owner:
        owner.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD 'disposable-test-only'").format(sql.Identifier(role)))
        try:
            monkeypatch.setattr(settings, 'EXTRACTION_QUOTA_ENABLED', with_quota)
            monkeypatch.setattr(settings, 'EXTRACTION_GLOBAL_TRIAL_MONTHLY_LIMIT', 1000000)
            monkeypatch.setattr(settings, 'EXTRACTION_GLOBAL_TRIAL_CALL_MONTHLY_LIMIT', 1000000)
            monkeypatch.setattr(settings, 'PROVIDER_CREDENTIAL_ENCRYPTION_KEY', base64.urlsafe_b64encode(b'p' * 32).decode())
            monkeypatch.setattr(settings, 'LANDINGAI_TRIAL_API_KEY', 'trial-test-key')
            with sessionmaker(bind=restricted_engine, autoflush=False)() as db:
                bind_session_to_org(db, org)
                if with_quota:
                    db.add(ProviderCredential(org_id=org, provider='landingai', ciphertext=encrypt_credential(
                        'trial-test-key', org, 'landingai', settings.PROVIDER_CREDENTIAL_ENCRYPTION_KEY)))
                    db.flush()
                job = create_workflow_job(db, {'job_id': job_id, 'filename': 'a.pdf', 'storage_key': 'test', 'content_type': 'application/pdf', 'size_bytes': 4, 'sha256': 'a' * 64}, org)
                attempt = job.selected_attempt_id
                db.commit()
            monkeypatch.setattr(settings, 'DATABASE_URL', TEST_DATABASE_URL)
            monkeypatch.setattr(sys, 'argv', ['provision_cloudflare_machine.py', role])
            runpy.run_path(str(root / 'deploy/storage/provision_cloudflare_machine.py'))
            role_url = make_url(TEST_DATABASE_URL).set(username=role, password='disposable-test-only').render_as_string(hide_password=False)
            with psycopg.connect(role_url, autocommit=True) as worker:
                for query in ('SELECT parsed_results FROM extraction_jobs LIMIT 1', 'SELECT ciphertext FROM provider_credentials LIMIT 1'):
                    with pytest.raises(psycopg.errors.InsufficientPrivilege):
                        worker.execute(query)
            engine = create_engine(role_url.replace('postgresql://', 'postgresql+psycopg://', 1))
            try:
                app = FastAPI(); app.include_router(router)
                app.dependency_overrides[transport_settings] = lambda: CloudflareTransportSettings(token, [key])
                app.dependency_overrides[session_factory] = lambda: sessionmaker(bind=engine, autoflush=False)
                client = TestClient(app)
                base = f'/cloudflare/jobs/{job_id}/attempts/{attempt}'
                headers = {'X-Extraction-Protocol': '2', 'Authorization': f'Bearer {token}', 'X-Dispatch-Capability': issue_capability(key, org, job_id, attempt, ttl_seconds=300)}
                claim = client.post(base + '/claim', headers=headers)
                assert claim.status_code == 200, claim.text
                headers['X-Checkpoint-Token'] = claim.json()['checkpoint_token']
                if with_quota:
                    credential = client.get(base + '/credential', headers=headers)
                    assert credential.status_code == 200, credential.text
                    assert credential.json() == {'api_key': 'trial-test-key'}
                    assert client.post(base + '/provider-start', headers=headers).status_code == 200
                event = {'schema_version':'1', 'job_id':job_id, 'attempt_id':attempt, 'event_id':'terminal', 'status':'completed', 'result':{'contract_data':{'contract_name':'Example'}, 'parties_data':[]}}
                if not with_quota:
                    assert client.post(base + '/checkpoint', headers=headers, json=event).status_code == 409
                    event.pop('result')
                    event.update(status='failed', error={'code': 'PREPARATION_FAILED', 'message': 'No reservation.', 'retryable': False})
                stored = client.post(base + '/checkpoint', headers=headers, json=event)
                assert stored.status_code == 200, stored.text
                delivered = client.post(base + '/deliver', headers=headers)
                assert delivered.status_code == 200, delivered.text
            finally:
                engine.dispose()
        finally:
            for table in ('workflow_receipts', 'cloudflare_executions', 'workflow_outbox'):
                owner.execute(sql.SQL('DELETE FROM {} WHERE attempt_id IN (SELECT attempt_id FROM extraction_attempts WHERE job_id=%s)').format(sql.Identifier(table)), (job_id,))
            owner.execute('DELETE FROM extraction_attempts WHERE job_id=%s', (job_id,))
            owner.execute('DELETE FROM extraction_jobs WHERE job_id=%s', (job_id,))
            owner.execute('DELETE FROM extraction_quota_reservations WHERE org_id=%s', (org,))
            owner.execute('DELETE FROM extraction_quota_org WHERE org_id=%s', (org,))
            owner.execute('DELETE FROM provider_credentials WHERE org_id=%s', (org,))
            owner.execute(sql.SQL('DROP OWNED BY {}').format(sql.Identifier(role)))
            owner.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(role)))
