from datetime import datetime, timedelta, timezone

import pytest

from app.core.auth import CurrentUser, get_current_user
from app.core.config import settings
from app.main import app
from conftest import ADMIN_PERMISSIONS, DEFAULT_TEST_ORG

BASE = '/api/organization'


@pytest.fixture
def org_client(client, monkeypatch):
    monkeypatch.setattr(settings, 'TRIAL_IDENTITY_HASH_KEY', 'lifecycle-test-secret')
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user_id='closing-admin', org_id=DEFAULT_TEST_ORG,
        permissions=ADMIN_PERMISSIONS + ['organization:close'])
    return client


def test_close_requires_confirmation_and_schedules_thirty_days(org_client):
    assert org_client.get(BASE + '/lifecycle').json() == {'status': 'active', 'purge_after': None}
    assert org_client.post(BASE + '/close', json={'confirm': 'wrong'}).status_code == 422
    before = datetime.now(timezone.utc)
    response = org_client.post(BASE + '/close', json={'confirm': 'CLOSE'})
    assert response.status_code == 200, response.text
    assert response.json()['status'] == 'closing'
    purge_after = datetime.fromisoformat(response.json()['purge_after'])
    assert before + timedelta(days=30) <= purge_after <= datetime.now(timezone.utc) + timedelta(days=30)
    assert org_client.get(BASE + '/lifecycle').json() == response.json()
    assert org_client.post(BASE + '/close', json={'confirm': 'CLOSE'}).json() == response.json()


@pytest.mark.parametrize('action', ['close', 'cancel-closure'])
def test_close_and_cancel_require_permission(client, action):
    response = client.post(BASE + '/' + action, json={'confirm': 'CLOSE'})
    assert response.status_code == 403


def _dependencies(dependant):
    for dependency in dependant.dependencies:
        yield dependency.call
        yield from _dependencies(dependency)


def test_all_org_routes_enforce_closure(org_client):
    import re
    from fastapi.routing import APIRoute
    exempt = {('GET', BASE + '/lifecycle'), ('POST', BASE + '/close'),
        ('POST', BASE + '/cancel-closure'), ('POST', '/api/members/me/leave'),
        ('GET', '/api/system/config')}
    response = org_client.post(BASE + '/close', json={'confirm': 'CLOSE'})
    purge_after = response.json()['purge_after']
    checked = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        dependencies = list(_dependencies(route.dependant))
        if get_current_user not in dependencies:
            continue
        for method in route.methods:
            if (method, route.path) in exempt:
                continue
            path = re.sub(r'\{[^}]+\}', '1', route.path)
            response = org_client.request(method, path, json={})
            assert response.status_code == 423, (method, path, response.text)
            assert response.json()['detail'] == {'code': 'ORGANIZATION_CLOSING', 'purge_after': purge_after}
            assert any(getattr(dep, '__name__', '') == 'require_active_organization' for dep in dependencies), route.path
            checked.append((method, route.path))
    assert len(checked) > 30
    assert org_client.get('/api/system/config').status_code == 200


def test_cancel_restores_access_and_preserves_data(org_client):
    contract = org_client.post('/api/contracts/', json={'contract_name': 'Keep this treaty', 'contract_number': 'CLOSE-TEST', 'effective_date': '2026-01-01', 'expiration_date': '2027-01-01'})
    assert contract.status_code == 201, contract.text
    saved = org_client.get('/api/contracts/' + str(contract.json()['id'])).json()
    assert org_client.post(BASE + '/close', json={'confirm': 'CLOSE'}).status_code == 200
    assert org_client.get('/api/contracts/').status_code == 423
    assert org_client.post(BASE + '/cancel-closure').json() == {'status': 'active', 'purge_after': None}
    assert org_client.get('/api/contracts/' + str(saved['id'])).json() == saved
    assert org_client.post(BASE + '/cancel-closure').status_code == 409


def test_close_cancels_work_releases_quota_and_fences_worker(org_client, db_session, monkeypatch):
    import base64
    import io
    from pypdf import PdfWriter
    from app.api.endpoints.cloudflare import machine_db
    from app.models.extraction_job import ExtractionJob
    from app.models.extraction_quota import GlobalQuota, OrganizationQuota, QuotaReservation
    from app.models.workflow import ExtractionAttempt
    from app.services.workflow_service import lease_dispatch
    from conftest import seed_trial_quota
    from test_trial_hardening import Store
    import app.services.private_document_service as documents

    for name, value in {'CLOUDFLARE_TRIAL_ENABLED': True, 'EXTRACTION_QUOTA_ENABLED': True,
        'EXTRACTION_GLOBAL_TRIAL_MONTHLY_LIMIT': 100000, 'EXTRACTION_GLOBAL_TRIAL_CALL_MONTHLY_LIMIT': 100000,
        'LANDINGAI_TRIAL_API_KEY': 'trial-key',
        'PROVIDER_CREDENTIAL_ENCRYPTION_KEY': base64.urlsafe_b64encode(b'a' * 32).decode()}.items():
        monkeypatch.setattr(settings, name, value)
    monkeypatch.setattr(documents, 'storage_service', Store())
    seed_trial_quota(db_session, DEFAULT_TEST_ORG)
    prior_global = db_session.get(GlobalQuota, 1)
    prior_pending = prior_global.trial_pending if prior_global else 0
    assert org_client.post('/api/provider-credentials/landingai/acknowledgment').status_code == 200
    stream = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.write(stream)
    ids = []
    for _ in range(2):
        response = org_client.post('/api/documents/upload', files={'file': ('test.pdf', stream.getvalue(), 'application/pdf')})
        assert response.status_code == 200, response.text
        job_id = response.json()['job_id']
        ids.append((job_id, db_session.get(ExtractionJob, job_id).selected_attempt_id))
    app.dependency_overrides[machine_db] = lambda: db_session
    try:
        base = '/api/cloudflare/jobs/' + ids[1][0] + '/attempts/' + ids[1][1]
        claim = org_client.post(base + '/claim', headers={'X-Extraction-Protocol': '2'})
        assert claim.json()['decision'] == 'start'
        token = claim.json()['checkpoint_token']
        assert org_client.post(base + '/provider-start', headers={'X-Checkpoint-Token': token}).status_code == 200
        assert [db_session.get(ExtractionAttempt, attempt).status for _, attempt in ids] == ['queued', 'processing']
        assert org_client.post(BASE + '/close', json={'confirm': 'CLOSE'}).status_code == 200
        for job_id, attempt in ids:
            assert db_session.get(ExtractionAttempt, attempt).status == 'cancelled'
            assert db_session.get(QuotaReservation, (DEFAULT_TEST_ORG, attempt)).status == 'failed'
            assert db_session.get(ExtractionJob, job_id).deleted_at is None
        quota = db_session.get(OrganizationQuota, DEFAULT_TEST_ORG)
        assert (quota.pending, quota.free_pending, quota.free_successes) == (0, 0, 0)
        assert db_session.get(GlobalQuota, 1).trial_pending == prior_pending
        assert lease_dispatch(db_session) is None
        assert org_client.post(base + '/claim', headers={'X-Extraction-Protocol': '2'}).json()['decision'] == 'closed'
        assert org_client.post(base + '/provider-start', headers={'X-Checkpoint-Token': token}).status_code == 409
        event = {'schema_version': '1', 'job_id': ids[1][0], 'attempt_id': ids[1][1],
            'event_id': 'terminal', 'status': 'completed', 'result': {'contract_data': {'contract_name': 'Late result'}, 'parties_data': []}}
        assert org_client.post(base + '/checkpoint', json=event, headers={'X-Checkpoint-Token': token}).status_code == 409
        assert org_client.post(BASE + '/cancel-closure').status_code == 200
        for job_id, _ in ids:
            status = org_client.get('/api/documents/status/' + job_id)
            assert status.json()['status'] == 'cancelled'
            assert status.json()['can_retry'] is False
    finally:
        app.dependency_overrides.pop(machine_db, None)


def test_cancel_after_deadline_is_rejected(org_client, db_session):
    from app.models.organization_lifecycle import OrganizationLifecycle
    assert org_client.post(BASE + '/close', json={'confirm': 'CLOSE'}).status_code == 200
    row = db_session.get(OrganizationLifecycle, DEFAULT_TEST_ORG)
    row.purge_after = datetime.now(timezone.utc) - timedelta(seconds=1)
    db_session.flush()
    assert org_client.post(BASE + '/cancel-closure').status_code == 409
    assert org_client.get(BASE + '/lifecycle').json()['status'] == 'closing'


def test_members_can_read_lifecycle_and_reach_leave_while_closing(org_client, monkeypatch):
    from fastapi import HTTPException
    from app.api.endpoints import members
    assert org_client.post(BASE + '/close', json={'confirm': 'CLOSE'}).status_code == 200
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user_id='viewer', org_id=DEFAULT_TEST_ORG, permissions=[])
    assert org_client.get(BASE + '/lifecycle').json()['status'] == 'closing'
    assert org_client.post(BASE + '/cancel-closure').status_code == 403
    def unavailable():
        raise HTTPException(409, 'Leave path reached')
    monkeypatch.setattr(members.settings, 'WORKOS_API_KEY', 'dummy-key')
    monkeypatch.setattr(members, '_workos_client', unavailable)
    assert org_client.post('/api/members/me/leave').status_code == 409


def test_closing_one_organization_does_not_lock_another(org_client, as_org, db_session):
    from uuid import uuid4
    from app.models.organization_lifecycle import OrganizationLifecycle
    import hashlib
    import hmac

    assert org_client.post(BASE + '/close', json={'confirm': 'CLOSE'}).status_code == 200
    row = db_session.get(OrganizationLifecycle, DEFAULT_TEST_ORG)
    assert row.requested_by_hash == hmac.new(b'lifecycle-test-secret', b'closing-admin', hashlib.sha256).hexdigest()
    other = as_org('active-' + uuid4().hex)
    assert other.get(BASE + '/lifecycle').json() == {'status': 'active', 'purge_after': None}
    assert other.get('/api/contracts/').status_code == 200
