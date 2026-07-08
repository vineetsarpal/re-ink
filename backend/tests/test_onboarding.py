"""
Organization provisioning for zero-org users.

A freshly signed-up user has no organization, so their token carries no org_id
and the backend rejects it. This endpoint gives them a dedicated organization
(named after their email) so every user ends up scoped to exactly one tenant.
The WorkOS client is stubbed — no network.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

import app.api.endpoints.onboarding as onboarding
from app.core.auth import CurrentUser, get_authenticated_user
from app.core.config import settings
from app.main import app

PROVISION_PATH = "/api/onboarding/provision-organization"


@pytest.fixture
def orgless_user(monkeypatch):
    # The provisioning endpoint requires WORKOS_API_KEY to be configured; set a
    # dummy so tests don't depend on a local .env (CI has none). The WorkOS
    # client itself is stubbed per test.
    monkeypatch.setattr(settings, "WORKOS_API_KEY", "dummy-key")
    app.dependency_overrides[get_authenticated_user] = lambda: CurrentUser(
        user_id="user_new", org_id=None
    )
    yield
    app.dependency_overrides.pop(get_authenticated_user, None)


def test_provision_creates_dedicated_org_named_after_email(orgless_user, monkeypatch):
    wos = MagicMock()
    wos.organization_membership.list_organization_memberships.return_value.data = []
    wos.user_management.get_user.return_value.email = "alice@acme.com"
    wos.organizations.list_organizations.return_value.data = []
    wos.organizations.create_organization.return_value.id = "org_new123"
    monkeypatch.setattr(onboarding, "_workos_client", lambda: wos)

    resp = TestClient(app).post(PROVISION_PATH)

    assert resp.status_code == 200, resp.text
    assert resp.json()["organization_id"] == "org_new123"
    wos.organizations.create_organization.assert_called_once_with(name="alice@acme.com")
    wos.organization_membership.create_organization_membership.assert_called_once_with(
        user_id="user_new", organization_id="org_new123", role="admin"
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
    wos.organizations.list_organizations.return_value.data = [org]
    monkeypatch.setattr(onboarding, "_workos_client", lambda: wos)

    resp = TestClient(app).post(PROVISION_PATH)

    assert resp.status_code == 200, resp.text
    assert resp.json()["organization_id"] == "org_acme"
    wos.organizations.list_organizations.assert_called_once_with(domains=["acme.com"])
    wos.organizations.create_organization.assert_not_called()
    wos.organization_membership.create_organization_membership.assert_called_once_with(
        user_id="user_new", organization_id="org_acme", role="viewer"
    )


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
    wos.organizations.list_organizations.return_value.data = orgs
    wos.organizations.create_organization.return_value.id = expected_org_id
    monkeypatch.setattr(onboarding, "_workos_client", lambda: wos)

    resp = TestClient(app).post(PROVISION_PATH)

    assert resp.status_code == 200, resp.text
    assert resp.json()["organization_id"] == expected_org_id
    wos.organizations.create_organization.assert_called_once_with(name="alice@acme.com")
    wos.organization_membership.create_organization_membership.assert_called_once_with(
        user_id="user_new", organization_id=expected_org_id, role="admin"
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


def test_provision_requires_authentication():
    """No token → 401, even though the endpoint allows orgless users."""
    assert TestClient(app).post(PROVISION_PATH).status_code == 401
