"""
Organization provisioning for zero-org users.

A freshly signed-up user has no organization, so their token carries no org_id
and the backend rejects it. This endpoint gives them a dedicated organization
(named after their email) so every user ends up scoped to exactly one tenant.
The WorkOS client is stubbed — no network.
"""
from __future__ import annotations

from unittest.mock import MagicMock, ANY
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import app.api.endpoints.onboarding as onboarding
from app.core.auth import CurrentUser, get_authenticated_user, get_current_user
from app.core.config import settings
from app.main import app

PROVISION_PATH = "/api/onboarding/provision-organization"


@pytest.fixture
def orgless_user(monkeypatch):
    # The provisioning endpoint requires WORKOS_API_KEY to be configured; set a
    # dummy so tests don't depend on a local .env (CI has none). The WorkOS
    # client itself is stubbed per test.
    monkeypatch.setattr(settings, "TRIAL_IDENTITY_HASH_KEY", "test-identity-key")
    monkeypatch.setattr(settings, "WORKOS_API_KEY", "dummy-key")
    user_id = "user-" + uuid4().hex
    app.dependency_overrides[get_authenticated_user] = lambda: CurrentUser(
        user_id=user_id, org_id=None
    )
    yield user_id
    app.dependency_overrides.pop(get_authenticated_user, None)


def test_provision_creates_dedicated_org_named_after_email(orgless_user, monkeypatch):
    wos = MagicMock()
    wos.organization_membership.list_organization_memberships.return_value.data = []
    wos.user_management.get_user.return_value.email = "alice@acme.com"
    wos.user_management.get_user.return_value.email_verified = True
    wos.organizations.list_organizations.return_value.data = []
    wos.organizations.create_organization.return_value.id = "org_new123"
    monkeypatch.setattr(onboarding, "_workos_client", lambda: wos)

    resp = TestClient(app).post(PROVISION_PATH)

    assert resp.status_code == 200, resp.text
    assert resp.json()["organization_id"] == "org_new123"
    wos.organizations.create_organization.assert_called_once_with(name="alice@acme.com", request_options={"idempotency_key": ANY})
    wos.organization_membership.create_organization_membership.assert_called_once_with(
        user_id=orgless_user, organization_id="org_new123", role="admin"
    )


def test_provision_joins_single_verified_domain_match_as_viewer(
    orgless_user, monkeypatch
):
    domain = MagicMock()
    domain.domain = "acme.com"
    domain.state = "verified"
    org = MagicMock()
    org.id = "org_acme"
    org.domains = [domain]

    wos = MagicMock()
    wos.organization_membership.list_organization_memberships.return_value.data = []
    wos.user_management.get_user.return_value.email = "alice@acme.com"
    wos.user_management.get_user.return_value.email_verified = True
    wos.organizations.list_organizations.return_value.data = [org]
    monkeypatch.setattr(onboarding, "_workos_client", lambda: wos)

    resp = TestClient(app).post(PROVISION_PATH)

    assert resp.status_code == 200, resp.text
    assert resp.json()["organization_id"] == "org_acme"
    wos.organizations.list_organizations.assert_called_once_with(domains=["acme.com"])
    wos.organizations.create_organization.assert_not_called()
    wos.organization_membership.create_organization_membership.assert_called_once_with(
        user_id=orgless_user, organization_id="org_acme", role="viewer"
    )


def test_unverified_email_cannot_provision_or_join_an_organization(orgless_user, monkeypatch):
    wos = MagicMock()
    wos.organization_membership.list_organization_memberships.return_value.data = []
    wos.user_management.get_user.return_value.email = "alice@acme.com"
    wos.user_management.get_user.return_value.email_verified = False
    monkeypatch.setattr(onboarding, "_workos_client", lambda: wos)

    response = TestClient(app).post(PROVISION_PATH)

    assert response.status_code == 403
    wos.organizations.create_organization.assert_not_called()
    wos.organization_membership.create_organization_membership.assert_not_called()


@pytest.mark.parametrize(
    ("domain_states", "expected_org_id"),
    [
        (["pending"], "org_solo_unverified"),
        (["verified", "verified"], "org_solo_ambiguous"),
    ],
)
def test_provision_falls_back_to_solo_admin_org_without_one_verified_domain_match(
    orgless_user, monkeypatch, domain_states, expected_org_id
):
    orgs = []
    for index, state in enumerate(domain_states, start=1):
        domain = MagicMock()
        domain.domain = "acme.com"
        domain.state = state
        org = MagicMock()
        org.id = f"org_match_{index}"
        org.domains = [domain]
        orgs.append(org)

    wos = MagicMock()
    wos.organization_membership.list_organization_memberships.return_value.data = []
    wos.user_management.get_user.return_value.email = "alice@acme.com"
    wos.user_management.get_user.return_value.email_verified = True
    wos.organizations.list_organizations.return_value.data = orgs
    wos.organizations.create_organization.return_value.id = expected_org_id
    monkeypatch.setattr(onboarding, "_workos_client", lambda: wos)

    resp = TestClient(app).post(PROVISION_PATH)

    assert resp.status_code == 200, resp.text
    assert resp.json()["organization_id"] == expected_org_id
    wos.organizations.create_organization.assert_called_once_with(name="alice@acme.com", request_options={"idempotency_key": ANY})
    wos.organization_membership.create_organization_membership.assert_called_once_with(
        user_id=orgless_user, organization_id=expected_org_id, role="admin"
    )


def test_provision_is_idempotent_for_existing_member(orgless_user, monkeypatch):
    membership = MagicMock()
    membership.organization_id = "org_existing"
    wos = MagicMock()
    wos.organization_membership.list_organization_memberships.return_value.data = [
        membership
    ]
    monkeypatch.setattr(onboarding, "_workos_client", lambda: wos)

    resp = TestClient(app).post(PROVISION_PATH)

    assert resp.status_code == 200
    assert resp.json()["organization_id"] == "org_existing"
    wos.organizations.create_organization.assert_not_called()
    wos.organization_membership.create_organization_membership.assert_not_called()


def test_concurrent_first_requests_create_only_one_organization(orgless_user, monkeypatch):
    wos = MagicMock()
    first_lookup = Event()
    second_lookup = Event()
    state_lock = Lock()
    memberships = []
    lookups = 0

    def list_memberships(**_kwargs):
        nonlocal lookups
        with state_lock:
            lookups += 1
            number = lookups
            snapshot = list(memberships)
        if number == 1:
            first_lookup.set()
            second_lookup.wait(1)
        else:
            second_lookup.set()
        return SimpleNamespace(data=snapshot)

    def create_membership(**kwargs):
        with state_lock:
            memberships.append(SimpleNamespace(organization_id=kwargs["organization_id"]))

    wos.organization_membership.list_organization_memberships.side_effect = list_memberships
    wos.organization_membership.create_organization_membership.side_effect = create_membership
    wos.user_management.get_user.return_value.email = "alice@acme.com"
    wos.user_management.get_user.return_value.email_verified = True
    wos.organizations.list_organizations.return_value.data = []
    wos.organizations.create_organization.return_value.id = "org_new123"
    monkeypatch.setattr(onboarding, "_workos_client", lambda: wos)

    def request():
        return TestClient(app).post(PROVISION_PATH)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(request)
        assert first_lookup.wait(3)
        second = executor.submit(request)
        responses = [first.result(timeout=5), second.result(timeout=5)]

    assert [response.json()["organization_id"] for response in responses] == ["org_new123"] * 2
    wos.organizations.create_organization.assert_called_once()
    wos.organization_membership.create_organization_membership.assert_called_once()


def test_provision_requires_authentication():
    """No token → 401, even though the endpoint allows orgless users."""
    assert TestClient(app).post(PROVISION_PATH).status_code == 401


def test_creation_timeout_retries_same_idempotency_key(orgless_user, monkeypatch, restricted_engine):
    wos = MagicMock()
    wos.organization_membership.list_organization_memberships.return_value.data = []
    wos.user_management.get_user.return_value.email = 'retry@gmail.com'
    wos.user_management.get_user.return_value.email_verified = True
    wos.organizations.list_organizations.return_value.data = []
    created = {}
    keys = []

    def create(**kwargs):
        from sqlalchemy.orm import Session
        from app.models.provisioning_intent import ProvisioningIntent
        with Session(restricted_engine) as db:
            intent = db.get(ProvisioningIntent, orgless_user)
            assert intent.state == 'pending'
            assert intent.created_at is not None
        key = kwargs['request_options']['idempotency_key']
        keys.append(key)
        org = created.setdefault(key, SimpleNamespace(id='org-timeout-' + orgless_user))
        if len(keys) == 1:
            raise TimeoutError('WorkOS created the organization but response was lost')
        return org

    wos.organizations.create_organization.side_effect = create
    monkeypatch.setattr(onboarding, '_workos_client', lambda: wos)
    client = TestClient(app, raise_server_exceptions=False)
    assert client.post(PROVISION_PATH).status_code == 500
    response = client.post(PROVISION_PATH)
    assert response.status_code == 200, response.text
    assert response.json()['organization_id'] == 'org-timeout-' + orgless_user
    assert len(created) == 1
    assert len(keys) == 2 and keys[0] == keys[1]


@pytest.mark.parametrize('membership_created', [False, True])
def test_retry_after_membership_failure_completes_trial_once(
    orgless_user, monkeypatch, restricted_engine, membership_created
):
    from sqlalchemy.orm import Session
    from app.core.tenancy import bind_session_to_org
    from app.models.provisioning_intent import ProvisioningIntent
    from app.services.extraction_quota import quota_usage, reserve_extraction

    org_id = 'org-recovery-' + uuid4().hex
    wos = MagicMock()
    memberships = []
    wos.organization_membership.list_organization_memberships.side_effect = lambda **kwargs: SimpleNamespace(data=list(memberships))
    wos.user_management.get_user.return_value.email = uuid4().hex + '@gmail.com'
    wos.user_management.get_user.return_value.email_verified = True
    wos.organizations.list_organizations.return_value.data = []
    wos.organizations.create_organization.return_value.id = org_id
    attempts = 0

    def membership(**kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            if membership_created:
                memberships.append(SimpleNamespace(organization_id=org_id))
            raise TimeoutError('Membership response lost')
        memberships.append(SimpleNamespace(organization_id=org_id))

    wos.organization_membership.create_organization_membership.side_effect = membership
    monkeypatch.setattr(onboarding, '_workos_client', lambda: wos)
    client = TestClient(app, raise_server_exceptions=False)
    assert client.post(PROVISION_PATH).status_code == 500
    with Session(restricted_engine) as db:
        intent = db.get(ProvisioningIntent, orgless_user)
        assert intent.state == 'org_created'
        assert intent.org_id == org_id
        bind_session_to_org(db, org_id)
        assert quota_usage(db, org_id).trial_eligible is False
    response = client.post(PROVISION_PATH)
    assert response.status_code == 200, response.text
    assert response.json()['organization_id'] == org_id
    wos.organizations.create_organization.assert_called_once()
    assert attempts == (1 if membership_created else 2)
    with Session(restricted_engine) as db:
        assert db.get(ProvisioningIntent, orgless_user).state == 'completed'
        bind_session_to_org(db, org_id)
        assert quota_usage(db, org_id).trial_eligible is True
        reserve_extraction(db, org_id, 'one', has_customer_key=False, global_trial_limit=100000)
        completed_at = db.get(ProvisioningIntent, orgless_user).updated_at
        assert client.post(PROVISION_PATH).json()['organization_id'] == org_id
        assert attempts == (1 if membership_created else 2)
        assert quota_usage(db, org_id).free_pending == 1
        db.refresh(db.get(ProvisioningIntent, orgless_user))
        assert db.get(ProvisioningIntent, orgless_user).updated_at == completed_at


@pytest.mark.parametrize('membership_state', ['removed', 'elsewhere', 'still_member'])
def test_completed_intent_follows_current_memberships(
    orgless_user, monkeypatch, restricted_engine, membership_state
):
    from sqlalchemy.orm import Session
    from app.core.tenancy import bind_session_to_org
    from app.models.provisioning_intent import ProvisioningIntent
    from app.services.extraction_quota import quota_usage

    original, replacement, other = [uuid4().hex for _ in range(3)]
    memberships = []
    wos = MagicMock()
    wos.organization_membership.list_organization_memberships.side_effect = lambda **kwargs: SimpleNamespace(data=list(memberships))
    wos.organization_membership.create_organization_membership.side_effect = lambda **kwargs: memberships.append(SimpleNamespace(organization_id=kwargs['organization_id']))
    wos.user_management.get_user.return_value.email = uuid4().hex + '@gmail.com'
    wos.user_management.get_user.return_value.email_verified = True
    wos.organizations.list_organizations.return_value.data = []
    wos.organizations.create_organization.side_effect = [SimpleNamespace(id=original), SimpleNamespace(id=replacement)]
    monkeypatch.setattr(onboarding, '_workos_client', lambda: wos)
    client = TestClient(app)
    assert client.post(PROVISION_PATH).json()['organization_id'] == original
    with Session(restricted_engine) as db:
        original_intent_id = db.get(ProvisioningIntent, orgless_user).intent_id
        bind_session_to_org(db, original)
        assert quota_usage(db, original).trial_eligible is True

    if membership_state == 'removed':
        memberships.clear()
        expected = replacement
    elif membership_state == 'elsewhere':
        memberships[:] = [SimpleNamespace(organization_id=other)]
        expected = other
    else:
        memberships.insert(0, SimpleNamespace(organization_id=other))
        expected = original
    response = client.post(PROVISION_PATH)
    assert response.status_code == 200, response.text
    assert response.json()['organization_id'] == expected
    with Session(restricted_engine) as db:
        intent = db.get(ProvisioningIntent, orgless_user)
        assert intent.org_id == expected
        assert intent.state == 'completed'
        if membership_state == 'removed':
            assert intent.intent_id != original_intent_id
            bind_session_to_org(db, replacement)
            assert quota_usage(db, replacement).trial_eligible is False
        else:
            assert intent.intent_id == original_intent_id
    calls = wos.organizations.create_organization.call_args_list
    assert len(calls) == (2 if membership_state == 'removed' else 1)
    if membership_state == 'removed':
        assert calls[0].kwargs['request_options']['idempotency_key'] != calls[1].kwargs['request_options']['idempotency_key']
    if membership_state == 'elsewhere':
        assert client.post(PROVISION_PATH).json()['organization_id'] == other


def test_leave_then_re_signup_is_trial_ineligible(
    orgless_user, monkeypatch, restricted_engine
):
    import app.api.endpoints.members as members
    from sqlalchemy import select
    from sqlalchemy.orm import Session
    from app.core.tenancy import bind_session_to_org
    from app.models.extraction_quota import TrialUser
    from app.models.provisioning_intent import ProvisioningIntent
    from app.services.extraction_quota import quota_usage

    original = 'org-original-' + uuid4().hex
    replacement = 'org-replacement-' + uuid4().hex
    memberships = []
    wos = MagicMock()

    def list_memberships(**kwargs):
        if 'organization_id' in kwargs:
            data = [
                membership for membership in memberships
                if membership.organization_id == kwargs['organization_id']
            ]
        else:
            data = [
                membership for membership in memberships
                if membership.user_id == kwargs['user_id']
            ]
        return SimpleNamespace(data=data)

    def create_membership(**kwargs):
        membership = SimpleNamespace(
            id='om-' + kwargs['organization_id'],
            user_id=kwargs['user_id'],
            organization_id=kwargs['organization_id'],
            role=SimpleNamespace(slug=kwargs['role']),
        )
        memberships.append(membership)
        return membership

    def delete_membership(membership_id):
        memberships[:] = [
            membership for membership in memberships if membership.id != membership_id
        ]

    wos.organization_membership.list_organization_memberships.side_effect = list_memberships
    wos.organization_membership.create_organization_membership.side_effect = create_membership
    def delete_user(user_id):
        memberships[:] = [
            membership for membership in memberships if membership.user_id != user_id
        ]

    wos.organization_membership.delete_organization_membership.side_effect = delete_membership
    wos.user_management.delete_user.side_effect = delete_user
    wos.user_management.get_user.return_value.email = uuid4().hex + '@gmail.com'
    wos.user_management.get_user.return_value.email_verified = True
    wos.organizations.list_organizations.return_value.data = []
    wos.organizations.create_organization.side_effect = [
        SimpleNamespace(id=original),
        SimpleNamespace(id=replacement),
    ]
    monkeypatch.setattr(onboarding, '_workos_client', lambda: wos)
    monkeypatch.setattr(members, '_workos_client', lambda: wos)
    client = TestClient(app)

    response = client.post(PROVISION_PATH)
    assert response.status_code == 200, response.text
    assert response.json()['organization_id'] == original
    with Session(restricted_engine) as db:
        bind_session_to_org(db, original)
        assert quota_usage(db, original).trial_eligible is True
        trial_user = db.scalars(
            select(TrialUser).where(TrialUser.org_id == original)
        ).one()
        user_hash = trial_user.user_hash

    memberships.append(SimpleNamespace(
        id='om-other-admin',
        user_id='other-admin',
        organization_id=original,
        role=SimpleNamespace(slug='admin'),
    ))
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user_id=orgless_user,
        org_id=original,
        role='admin',
        permissions=[],
    )
    try:
        response = client.post('/api/members/me/leave')
        assert response.status_code == 200, response.text
        assert response.json() == {'account_deleted': True}
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    wos.user_management.delete_user.assert_called_once_with(orgless_user)
    with Session(restricted_engine) as db:
        assert db.get(ProvisioningIntent, orgless_user) is None
        assert db.get(TrialUser, user_hash) is not None

    response = client.post(PROVISION_PATH)
    assert response.status_code == 200, response.text
    assert response.json()['organization_id'] == replacement
    with Session(restricted_engine) as db:
        bind_session_to_org(db, replacement)
        assert quota_usage(db, replacement).trial_eligible is False
        assert db.get(TrialUser, user_hash).org_id == original
