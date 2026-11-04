"""Committed restricted-PostgreSQL API checks with explicit workflow/storage fakes.

No live provider, WorkOS, R2 or VPS gate is satisfied by deterministic fixtures.
"""
from datetime import timedelta
from pathlib import Path
import importlib
import uuid
import httpx
import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import delete, event, select
from sqlalchemy.orm import sessionmaker
from app import worker
from app.core.auth import CurrentUser, get_current_user
from app.core.config import settings
from app.core.service_auth import get_workflow_db, require_workflow_service
from app.core.tenancy import get_tenant_db
from app.db.database import get_db
from app.main import app
from app.models.contract import Contract, contract_parties
from app.models.party import Party
from app.models.extraction_job import ExtractionJob
from app.models.workflow import ExtractionAttempt, WorkflowOutbox, WorkflowReceipt, StorageCleanup
from app.services import workflow_service as svc
from app.services.storage_service import StorageError

CORPUS = Path(__file__).parent / 'corpus'
BASE = '/api/workflows/extraction'

@pytest.fixture
def harness(restricted_engine, monkeypatch):
    org = 'acceptance-' + uuid.uuid4().hex
    for name, value in {'WORKFLOW_CUSTOMER_ORG_ID': org, 'WORKFLOW_UPLOADS_ENABLED': True,
        'WORKFLOW_WEBHOOK_URL': 'https://n8n.example.invalid/webhook',
        'WORKFLOW_SERVICE_TOKEN': 's'*32, 'WORKFLOW_DISPATCH_TOKEN': 'd'*32}.items():
        monkeypatch.setattr(settings, name, value)
    factory = sessionmaker(bind=restricted_engine, autoflush=False, expire_on_commit=False)
    opened = []
    def make(org_id=org):
        db = factory()
        @event.listens_for(db, 'after_begin')
        def scope(session, transaction, connection):
            connection.exec_driver_sql("SELECT set_config('app.current_org', %s, true)", (org_id,))
        opened.append(db)
        return db
    def dependency():
        db = make()
        try: yield db
        finally: db.close()
    def machine_dependency(identity=Depends(require_workflow_service)):
        yield from dependency()
    permissions = ['document:upload', 'review:approve', 'contract:read', 'party:read']
    def human(): return CurrentUser(user_id='synthetic-reviewer', org_id=org, permissions=permissions)
    old = app.dependency_overrides.copy()
    for dep in (get_tenant_db, get_db): app.dependency_overrides[dep] = dependency
    app.dependency_overrides[get_workflow_db] = machine_dependency
    app.dependency_overrides[get_current_user] = human
    class Store:
        def __init__(self): self.objects = {}; self.deleted = []
        def put(self, key, data, content_type): self.objects[key] = data
        def get(self, key):
            assert not any(db.in_transaction() for db in opened), 'storage fetch held transaction'
            return self.objects[key]
        def delete(self, key): self.deleted.append(key); self.objects.pop(key, None)
    store = Store()
    monkeypatch.setattr(importlib.import_module('app.services.document_service'), 'storage_service', store)
    class Harness: pass
    h = Harness()
    h.client, h.make, h.org = TestClient(app), make, org
    h.store, h.permissions, h.human, h.opened = store, permissions, human, opened
    h.headers = {'Authorization': 'Bearer ' + 's'*32}
    yield h
    app.dependency_overrides.clear(); app.dependency_overrides.update(old)
    for db in opened: db.close()
    db = make()
    for model in (WorkflowReceipt, WorkflowOutbox, ExtractionAttempt, StorageCleanup, ExtractionJob): db.execute(delete(model))
    db.execute(delete(contract_parties)); db.execute(delete(Contract)); db.execute(delete(Party))
    db.commit(); db.close()


def upload(h, filename='ordinary.pdf'):
    data = (CORPUS / filename).read_bytes()
    response = h.client.post('/api/documents/upload', files={'file': (filename, data)})
    assert response.status_code == 200, response.text
    job_id = response.json()['job_id']
    db = h.make()
    job = db.get(ExtractionJob, job_id)
    attempt_id = job.selected_attempt_id
    assert db.get(ExtractionAttempt, attempt_id) and db.get(WorkflowOutbox, attempt_id)
    assert job.storage_key in h.store.objects
    db.close()
    return job_id, attempt_id, data


def complete(job_id, attempt_id):
    return {'schema_version': '1', 'job_id': job_id, 'attempt_id': attempt_id,
            'event_id': 'result-' + uuid.uuid4().hex, 'status': 'completed',
            'result': {'contract_data': {'contract_number': 'SYN-001', 'contract_name': 'Synthetic Cedar Treaty',
                        'currency': 'USD', 'effective_date': '2027-01-01', 'expiration_date': '2027-12-31'},
                       'parties_data': [{'name': 'Cedar Example Insurance Ltd', 'role': 'cedant'}]}}

@pytest.mark.parametrize('filename', ['ordinary.pdf', 'docx.docx'])
def test_committed_upload_worker_claim_original_callback_review_correction_approval(harness, filename):
    h = harness
    job_id, attempt_id, original = upload(h, filename)
    callback = complete(job_id, attempt_id)
    class Workflow:
        def post(self, url, json, headers):
            assert not any(db.in_transaction() for db in h.opened), 'HTTP held transaction'
            assert headers['Authorization'] == 'Bearer ' + 'd'*32
            assert json['job_id'] == job_id
            path = f'{BASE}/jobs/{job_id}/attempts/{attempt_id}/claim'
            owner = h.client.post(path, headers=h.headers, json={'schema_version': '1', 'execution_key': 'synthetic-run'})
            assert owner.status_code == 200, owner.text
            assert owner.json()['decision'] == 'run'
            duplicate = h.client.post(path, headers=h.headers, json={'schema_version': '1', 'execution_key': 'duplicate-run'})
            assert duplicate.json()['decision'] == 'already_claimed'
            document = h.client.get(f'{BASE}/jobs/{job_id}/document?attempt_id={attempt_id}', headers=h.headers)
            assert document.status_code == 200, document.text
            assert document.content == original
            result = h.client.post(f'{BASE}/events', headers=h.headers, json=callback)
            assert result.status_code == 200, result.text
            assert h.client.post(f'{BASE}/events', headers=h.headers, json=callback).json() == result.json()
            return httpx.Response(202, json={'schema_version': '1', 'job_id': job_id, 'attempt_id': attempt_id, 'status': 'accepted'})
    assert worker.dispatch_once(h.make, Workflow())
    assert h.client.get(f'/api/documents/status/{job_id}').json()['status'] == 'completed'
    result = h.client.get(f'/api/documents/results/{job_id}').json()
    assert result['field_sources'] is None
    db = h.make()
    assert db.scalar(select(Contract)) is None and db.scalar(select(Party)) is None
    db.close()
    contract = result['contract_data']; contract['contract_name'] = 'Human corrected treaty name'
    review = {'contract': contract, 'parties': [{'action': 'create_new', 'role': 'cedant', 'party_data': {'name': 'Cedar Example Insurance Ltd'}}]}
    h.permissions.remove('review:approve')
    assert h.client.post('/api/review/approve', json=review).status_code == 403
    h.permissions.append('review:approve')
    approved = h.client.post('/api/review/approve', json=review)
    assert approved.status_code == 200, approved.text
    db = h.make()
    assert db.get(Contract, approved.json()['contract_id']).contract_name == 'Human corrected treaty name'
    assert db.scalar(select(contract_parties.c.role)) == 'cedant'
    db.close()


def test_machine_auth_cross_org_malformed_payload_and_no_human_approval(harness):
    h = harness
    job_id, attempt_id, _ = upload(h)
    callback = complete(job_id, attempt_id)
    for headers in ({}, {'Authorization': 'Bearer wrong'}, {'Authorization': 'Bearer ' + 'd'*32}):
        assert h.client.post(f'{BASE}/events', headers=headers, json=callback).status_code == 401
        assert h.client.post(f'{BASE}/jobs/{job_id}/attempts/{attempt_id}/claim', headers=headers, json={'schema_version': '1', 'execution_key': 'run'}).status_code == 401
        assert h.client.get(f'{BASE}/jobs/{job_id}/document?attempt_id={attempt_id}', headers=headers).status_code == 401
    assert h.client.post(f'{BASE}/events', headers=h.headers, json=dict(callback, schema_version='unsupported')).status_code == 422
    other = h.make('other-' + h.org)
    foreign = svc.create_workflow_job(other, {'job_id': uuid.uuid4().hex, 'filename': 'foreign.pdf', 'storage_key': 'foreign', 'content_type': 'application/pdf', 'size_bytes': 1, 'sha256': 'a'*64}, 'other-' + h.org)
    foreign_id, foreign_attempt = foreign.job_id, foreign.selected_attempt_id
    other.commit(); other.close()
    try:
        assert h.client.post(f'{BASE}/jobs/{foreign_id}/attempts/{foreign_attempt}/claim', headers=h.headers, json={'schema_version': '1', 'execution_key': 'run'}).status_code == 404
        assert h.client.get(f'{BASE}/jobs/{foreign_id}/document?attempt_id={foreign_attempt}', headers=h.headers).status_code == 404
        assert h.client.post(f'{BASE}/events', headers=h.headers, json=complete(foreign_id, foreign_attempt)).status_code == 404
    finally:
        other = h.make('other-' + h.org)
        for model in (WorkflowReceipt, WorkflowOutbox, ExtractionAttempt, ExtractionJob): other.execute(delete(model))
        other.commit(); other.close()
    db = h.make()
    assert db.get(ExtractionJob, job_id).status == 'queued'
    assert db.scalar(select(WorkflowReceipt)) is None
    assert db.get(ExtractionAttempt, attempt_id).execution_key is None
    db.close()
    app.dependency_overrides.pop(get_current_user)
    assert h.client.post('/api/review/approve', headers=h.headers, json={'contract': {}, 'parties': []}).status_code in (401, 403)


def test_timeout_polling_manual_retry_stale_callback_and_deletion(harness):
    h = harness
    job_id, attempt_id, _ = upload(h)
    db = h.make(); db.get(ExtractionAttempt, attempt_id).deadline_at = svc.now(db) - timedelta(seconds=1)
    db.commit(); db.close()
    assert h.client.get(f'/api/documents/status/{job_id}').json()['status'] == 'timed_out'
    h.permissions.remove('document:upload')
    assert h.client.post(f'/api/documents/{job_id}/retry').status_code == 403
    h.permissions.append('document:upload')
    assert h.client.post(f'/api/documents/{job_id}/retry').status_code == 200
    assert h.client.post(f'{BASE}/events', headers=h.headers, json=complete(job_id, attempt_id)).status_code == 409
    assert h.client.delete(f'/api/documents/{job_id}').status_code == 200
    assert h.client.get(f'/api/documents/status/{job_id}').status_code == 404
    assert h.client.post(f'{BASE}/events', headers=h.headers, json=complete(job_id, attempt_id)).status_code in (404, 410)
    db = h.make()
    assert db.scalar(select(Contract)) is None and db.scalar(select(Party)) is None
    db.close()


def test_failed_storage_creates_no_runnable_work(harness, monkeypatch):
    h = harness
    def fail(*args): raise StorageError('synthetic storage failure')
    monkeypatch.setattr(h.store, 'put', fail)
    response = h.client.post('/api/documents/upload', files={'file': ('ordinary.pdf', (CORPUS/'ordinary.pdf').read_bytes())})
    assert response.status_code == 503
    db = h.make()
    for model in (ExtractionJob, ExtractionAttempt, WorkflowOutbox): assert db.scalar(select(model)) is None
    db.close()

@pytest.mark.parametrize('commit_reached_server', [False, True])
def test_upload_commit_failure_proves_absence_before_orphan_deletion(harness, monkeypatch, commit_reached_server):
    h = harness
    def dependency():
        db = h.make(); real_commit = db.commit
        def fail_commit():
            if commit_reached_server: real_commit()
            raise RuntimeError('synthetic lost commit response')
        monkeypatch.setattr(db, 'commit', fail_commit)
        try: yield db
        finally: db.close()
    app.dependency_overrides[get_tenant_db] = dependency
    response = h.client.post('/api/documents/upload', files={'file': ('ordinary.pdf', (CORPUS/'ordinary.pdf').read_bytes())})
    assert response.status_code == 503
    db = h.make(); jobs = list(db.scalars(select(ExtractionJob)))
    assert bool(jobs) == commit_reached_server
    assert bool(h.store.objects) == commit_reached_server
    assert bool(h.store.deleted) != commit_reached_server
    db.close()


def test_concurrent_endpoint_claims_and_retries_use_independent_committed_sessions(harness):
    from concurrent.futures import ThreadPoolExecutor
    h = harness
    job_id, attempt_id, _ = upload(h)
    path = f'{BASE}/jobs/{job_id}/attempts/{attempt_id}/claim'
    def claim(key):
        return TestClient(app).post(path, headers=h.headers, json={'schema_version': '1', 'execution_key': key}).json()['decision']
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(claim, ['owner-a', 'owner-b'])) == ['already_claimed', 'run']
    failed = {'schema_version': '1', 'job_id': job_id, 'attempt_id': attempt_id, 'event_id': 'failure',
              'status': 'failed', 'error': {'code': 'UNREADABLE_DOCUMENT', 'message': 'No readable contract.', 'retryable': False}}
    assert h.client.post(f'{BASE}/events', headers=h.headers, json=failed).status_code == 200
    def retry(_): return TestClient(app).post(f'/api/documents/{job_id}/retry').status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(retry, [0, 1])) == [200, 409]
    db = h.make()
    assert len(list(db.scalars(select(ExtractionAttempt).where(ExtractionAttempt.job_id == job_id)))) == 2
    assert db.scalar(select(Contract)) is None and db.scalar(select(Party)) is None
    db.close()


def test_precommit_database_failure_and_failed_orphan_cleanup_do_not_queue_work(harness, monkeypatch):
    h = harness
    documents = importlib.import_module('app.api.endpoints.documents')
    def fail_db(*args): raise RuntimeError('synthetic precommit failure')
    def fail_cleanup(*args): raise StorageError('synthetic cleanup outage')
    monkeypatch.setattr(documents, 'create_workflow_job', fail_db)
    monkeypatch.setattr(h.store, 'delete', fail_cleanup)
    response = h.client.post('/api/documents/upload', files={'file': ('ordinary.pdf', (CORPUS/'ordinary.pdf').read_bytes())})
    assert response.status_code == 503 and len(h.store.objects) == 1
    db = h.make()
    for model in (ExtractionJob, ExtractionAttempt, WorkflowOutbox): assert db.scalar(select(model)) is None
    db.close()


def test_ambiguous_commit_and_unavailable_absence_probe_preserves_original(harness, monkeypatch):
    h = harness
    def dependency():
        db = h.make()
        def fail_commit(): raise RuntimeError('synthetic ambiguous DB disconnect')
        def fail_query(*args): raise RuntimeError('synthetic DB still unavailable')
        monkeypatch.setattr(db, 'commit', fail_commit)
        monkeypatch.setattr(db, 'query', fail_query)
        try: yield db
        finally: db.close()
    app.dependency_overrides[get_tenant_db] = dependency
    response = h.client.post('/api/documents/upload', files={'file': ('ordinary.pdf', (CORPUS/'ordinary.pdf').read_bytes())})
    assert response.status_code == 503 and len(h.store.objects) == 1 and not h.store.deleted
