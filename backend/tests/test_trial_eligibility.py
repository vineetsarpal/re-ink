from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.endpoints import onboarding
from app.core.auth import CurrentUser, get_authenticated_user
from app.core.config import settings
from app.core.tenancy import bind_session_to_org
from app.db.database import get_db
from app.main import app
from app.services.extraction_quota import reserve_extraction


@pytest.mark.parametrize(("same_user", "emails", "eligible"), [
    (True, ("alice@first.example", "alice@second.example"), False),
    (False, ("alice@ACME.example", "bob@acme.EXAMPLE"), False),
    (False, ("alice@GMAIL.COM", "bob@gmail.com"), True),
])
def test_provisioned_organizations_obey_trial_rules(db_session, monkeypatch, same_user, emails, eligible):
    user_id = uuid4().hex
    wos = MagicMock()
    wos.organization_membership.list_organization_memberships.return_value.data = []
    wos.user_management.get_user.return_value.email = emails[0]
    wos.user_management.get_user.return_value.email_verified = True
    wos.organizations.list_organizations.return_value.data = []
    orgs = ['first-' + uuid4().hex, 'second-' + uuid4().hex]
    wos.organizations.create_organization.side_effect = [type('Org', (), {'id': org})() for org in orgs]
    monkeypatch.setattr(onboarding, '_workos_client', lambda: wos)
    monkeypatch.setattr(settings, 'TRIAL_IDENTITY_HASH_KEY', 'test-identity-key')
    monkeypatch.setattr(settings, 'WORKOS_API_KEY', 'fake')
    app.dependency_overrides[get_authenticated_user] = lambda: CurrentUser(user_id=user_id, org_id=None)
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        client = TestClient(app)
        for index, org in enumerate(orgs):
            wos.user_management.get_user.return_value.email = emails[index]
            active_user = user_id if same_user or index == 0 else uuid4().hex
            app.dependency_overrides[get_authenticated_user] = lambda: CurrentUser(user_id=active_user, org_id=None)
            assert client.post('/api/onboarding/provision-organization').json()['organization_id'] == org
        bind_session_to_org(db_session, orgs[0])
        assert reserve_extraction(db_session, orgs[0], 'one', has_customer_key=False, global_trial_limit=100000).funding == 'trial'
        bind_session_to_org(db_session, orgs[1])
        if eligible:
            assert reserve_extraction(db_session, orgs[1], "two", has_customer_key=False, global_trial_limit=100000).funding == "trial"
            return
        with pytest.raises(HTTPException) as error:
            reserve_extraction(db_session, orgs[1], 'two', has_customer_key=False, global_trial_limit=100000)
        assert error.value.detail == {'code': 'TRIAL_NOT_ELIGIBLE', 'message': 'Free extractions are not available for this organization; add a LandingAI key'}
        assert reserve_extraction(db_session, orgs[1], 'customer', has_customer_key=True, global_trial_limit=0).funding == 'customer'
    finally:
        app.dependency_overrides.pop(get_authenticated_user, None)
        app.dependency_overrides.pop(get_db, None)


def test_ineligible_upload_reports_zero_free_remaining(as_org, db_session, monkeypatch):
    from app.models.extraction_quota import OrganizationQuota
    from datetime import date

    org = 'ineligible-' + uuid4().hex
    client = as_org(org)
    bind_session_to_org(db_session, org)
    db_session.add(OrganizationQuota(org_id=org, month=date.today().replace(day=1),
        trial_eligible=False, monthly_successes=0, monthly_attempts=0, pending=0,
        free_successes=0, free_pending=0))
    db_session.flush()
    monkeypatch.setattr(settings, 'EXTRACTION_QUOTA_ENABLED', True)
    monkeypatch.setattr(settings, 'CLOUDFLARE_TRIAL_ENABLED', True)
    usage = client.get('/api/documents/usage').json()
    assert usage['free_remaining'] == 0
    assert usage['has_customer_key'] is False
    assert client.post('/api/provider-credentials/landingai/acknowledgment').status_code == 200
    response = client.post('/api/documents/upload', files={'file': ('sample.pdf', b'fake', 'application/pdf')})
    assert response.status_code == 403
    assert response.json()['detail'] == {'code': 'TRIAL_NOT_ELIGIBLE', 'message': 'Free extractions are not available for this organization; add a LandingAI key'}


@pytest.mark.parametrize('read_only', [False, True])
def test_ineligible_precheck_rejects_trial_but_accepts_customer(db_session, read_only):
    from app.models.extraction_quota import OrganizationQuota
    from app.services.extraction_quota import precheck_extraction
    from datetime import date

    org = uuid4().hex
    bind_session_to_org(db_session, org)
    db_session.add(OrganizationQuota(org_id=org, trial_eligible=False, month=date.today().replace(day=1),
        monthly_successes=0, monthly_attempts=0, pending=0, free_successes=0, free_pending=0))
    db_session.flush()
    with pytest.raises(HTTPException) as error:
        precheck_extraction(db_session, org, has_customer_key=False, global_trial_limit=100, read_only=read_only)
    assert error.value.status_code == 403
    assert error.value.detail['code'] == 'TRIAL_NOT_ELIGIBLE'
    precheck_extraction(db_session, org, has_customer_key=True, global_trial_limit=0, read_only=read_only)


def test_verified_domain_join_preserves_users_future_trial(db_session, monkeypatch):
    from types import SimpleNamespace
    from app.services.trial_eligibility import assign_trial_eligibility

    user = uuid4().hex
    shared, dedicated = uuid4().hex, uuid4().hex
    monkeypatch.setattr(settings, 'WORKOS_API_KEY', 'fake')
    monkeypatch.setattr(settings, 'TRIAL_IDENTITY_HASH_KEY', 'test-identity-key')
    assign_trial_eligibility(db_session, shared, uuid4().hex, 'owner@shared.example')
    wos = MagicMock()
    wos.organization_membership.list_organization_memberships.return_value.data = []
    wos.user_management.get_user.return_value.email = 'joiner@shared.example'
    wos.user_management.get_user.return_value.email_verified = True
    wos.organizations.list_organizations.return_value.data = [SimpleNamespace(id=shared,
        domains=[SimpleNamespace(domain='shared.example', state='verified')])]
    monkeypatch.setattr(onboarding, '_workos_client', lambda: wos)
    app.dependency_overrides[get_authenticated_user] = lambda: CurrentUser(user_id=user, org_id=None)
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        client = TestClient(app)
        assert client.post('/api/onboarding/provision-organization').json()['organization_id'] == shared
        bind_session_to_org(db_session, shared)
        assert reserve_extraction(db_session, shared, 'shared', has_customer_key=False, global_trial_limit=100000).funding == 'trial'
        wos.organizations.list_organizations.return_value.data = []
        wos.user_management.get_user.return_value.email = 'joiner@gmail.com'
        wos.organizations.create_organization.return_value.id = dedicated
        assert client.post('/api/onboarding/provision-organization').json()['organization_id'] == dedicated
        bind_session_to_org(db_session, dedicated)
        assert reserve_extraction(db_session, dedicated, 'dedicated', has_customer_key=False, global_trial_limit=100000).funding == 'trial'
    finally:
        app.dependency_overrides.pop(get_authenticated_user, None)
        app.dependency_overrides.pop(get_db, None)


def test_schema_only_migration_and_idempotent_backfill(monkeypatch):
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import Session
    from conftest import TEST_DATABASE_URL
    from app.services.trial_eligibility import assign_trial_eligibility

    spec = importlib.util.spec_from_file_location('eligibility_migration',
        Path(__file__).parents[1] / 'alembic/versions/0017_trial_eligibility.py')
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine(TEST_DATABASE_URL.replace('postgresql://', 'postgresql+psycopg://'))
    monkeypatch.setattr(settings, 'TRIAL_IDENTITY_HASH_KEY', 'backfill-key')
    wos = MagicMock()
    wos.user_management.get_user.return_value.email = 'admin@legacy.example'
    monkeypatch.setattr('workos.WorkOSClient', lambda **kwargs: wos)
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                monkeypatch.setattr(migration, 'op', Operations(MigrationContext.configure(connection)))
                migration.downgrade()
                connection.execute(text("INSERT INTO extraction_quota_org (org_id, month, monthly_successes, monthly_attempts, pending, free_successes, free_pending) VALUES ('legacy', CURRENT_DATE, 1, 1, 0, 1, 0)"))
                connection.execute(text("INSERT INTO provider_acknowledgments (org_id, provider, notice_version, acknowledged_by) VALUES ('legacy', 'landingai', 'v1', 'legacy-user')"))
                monkeypatch.setattr(settings, 'TRIAL_IDENTITY_HASH_KEY', '')
                monkeypatch.setattr('workos.WorkOSClient', lambda **kwargs: pytest.fail('Migration must not call WorkOS'))
                migration.upgrade()
                assert connection.scalar(text("SELECT trial_eligible FROM extraction_quota_org WHERE org_id = 'legacy'")) is True
                connection.execute(text("INSERT INTO extraction_quota_org (org_id, month, monthly_successes, monthly_attempts, pending, free_successes, free_pending) VALUES ('new-default', CURRENT_DATE, 0, 0, 0, 0, 0)"))
                assert connection.scalar(text("SELECT trial_eligible FROM extraction_quota_org WHERE org_id = 'new-default'")) is False
                backfill_spec = importlib.util.spec_from_file_location('backfill',
                    Path(__file__).parents[2] / 'deploy/backfill_trial_eligibility.py')
                backfill = importlib.util.module_from_spec(backfill_spec)
                backfill_spec.loader.exec_module(backfill)
                backfill.backfill_trial_eligibility(connection, wos, 'backfill-key')
                backfill.backfill_trial_eligibility(connection, wos, 'backfill-key')
                assert connection.scalar(text("SELECT count(*) FROM trial_users WHERE org_id = 'legacy'")) == 1
                assert connection.scalar(text("SELECT count(*) FROM trial_domains WHERE org_id = 'legacy'")) == 1
                monkeypatch.setattr(settings, 'TRIAL_IDENTITY_HASH_KEY', 'backfill-key')
                with Session(bind=connection) as db:
                    for org, user, email in [('repeat-user', 'legacy-user', 'admin@gmail.com'),
                                              ('repeat-domain', 'new-user', 'other@LEGACY.EXAMPLE')]:
                        assign_trial_eligibility(db, org, user, email)
                        with pytest.raises(HTTPException) as error:
                            reserve_extraction(db, org, 'new', has_customer_key=False, global_trial_limit=100000)
                        assert error.value.detail['code'] == 'TRIAL_NOT_ELIGIBLE'
            finally:
                transaction.rollback()
    finally:
        engine.dispose()


@pytest.mark.parametrize('seam', ['reserve', 'precheck', 'readonly'])
def test_unprovisioned_org_denies_trial_but_accepts_customer(db_session, seam):
    from app.services.extraction_quota import precheck_extraction, quota_usage
    org = uuid4().hex
    bind_session_to_org(db_session, org)
    assert quota_usage(db_session, org).trial_eligible is False
    def admit(has_key):
        options = dict(has_customer_key=has_key, global_trial_limit=100000)
        if seam == 'reserve':
            return reserve_extraction(db_session, org, 'attempt', **options)
        return precheck_extraction(db_session, org, read_only=seam == 'readonly', **options)
    with pytest.raises(HTTPException) as error:
        admit(False)
    assert error.value.status_code == 403
    assert error.value.detail['code'] == 'TRIAL_NOT_ELIGIBLE'
    admit(True)


def test_usage_reports_existing_customer_key(as_org, db_session, monkeypatch):
    from app.models.provider_credential import ProviderCredential
    org = uuid4().hex
    client = as_org(org)
    bind_session_to_org(db_session, org)
    db_session.add(ProviderCredential(org_id=org, provider='landingai', ciphertext=b'encrypted'))
    db_session.flush()
    monkeypatch.setattr(settings, 'CLOUDFLARE_TRIAL_ENABLED', True)
    usage = client.get('/api/documents/usage').json()
    assert usage['has_customer_key'] is True
    assert usage['trial_eligible'] is False
