"""
Organization member-management endpoints.

WorkOS is stubbed at the API boundary; tests exercise FastAPI behavior,
permission checks, WorkOS call arguments, and last-admin guards without network.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from app.core.auth import CurrentUser, get_current_user
from app.core.config import settings
from app.main import app

MEMBERS_PATH = "/api/members"


def _clear_overrides() -> None:
    app.dependency_overrides.pop(get_current_user, None)


def _client_as(*, user_id: str = "user_admin", permissions: list[str]) -> TestClient:
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user_id=user_id,
        org_id="org_members",
        role="admin",
        permissions=permissions,
    )
    return TestClient(app)


def _role(slug: str):
    role = MagicMock()
    role.slug = slug
    return role


def _user(user_id: str, email: str, *, first_name: str | None = None, last_name: str | None = None):
    user = MagicMock()
    user.id = user_id
    user.email = email
    user.first_name = first_name
    user.last_name = last_name
    return user


def _membership(
    membership_id: str,
    user_id: str,
    role: str,
    *,
    email: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
):
    membership = MagicMock()
    membership.id = membership_id
    membership.user_id = user_id
    membership.organization_id = "org_members"
    membership.role = _role(role)
    membership.user = (
        _user(user_id, email, first_name=first_name, last_name=last_name)
        if email
        else None
    )
    return membership


def test_members_list_returns_hydrated_members(monkeypatch) -> None:
    import app.api.endpoints.members as members

    try:
        monkeypatch.setattr(settings, "WORKOS_API_KEY", "dummy-key")
        wos = MagicMock()
        wos.organization_membership.list_organization_memberships.return_value.data = [
            _membership(
                "om_admin",
                "user_admin",
                "admin",
                email="ada@example.com",
                first_name="Ada",
                last_name="Lovelace",
            ),
            _membership(
                "om_member",
                "user_member",
                "member",
                email="grace@example.com",
                first_name="Grace",
                last_name="Hopper",
            ),
        ]
        monkeypatch.setattr(members, "_workos_client", lambda: wos)
        client = _client_as(permissions=["member:manage"])

        resp = client.get(MEMBERS_PATH)

        assert resp.status_code == 200, resp.text
        assert resp.json() == {
            "members": [
                {
                    "id": "om_admin",
                    "user_id": "user_admin",
                    "email": "ada@example.com",
                    "first_name": "Ada",
                    "last_name": "Lovelace",
                    "role": "admin",
                },
                {
                    "id": "om_member",
                    "user_id": "user_member",
                    "email": "grace@example.com",
                    "first_name": "Grace",
                    "last_name": "Hopper",
                    "role": "member",
                },
            ]
        }
        wos.organization_membership.list_organization_memberships.assert_called_once_with(
            organization_id="org_members"
        )
    finally:
        _clear_overrides()


def test_member_invite_sends_workos_invitation_with_selected_role(monkeypatch) -> None:
    import app.api.endpoints.members as members

    try:
        monkeypatch.setattr(settings, "WORKOS_API_KEY", "dummy-key")
        wos = MagicMock()
        wos.user_management.send_invitation.return_value.id = "inv_123"
        wos.user_management.send_invitation.return_value.email = "new@example.com"
        wos.user_management.send_invitation.return_value.organization_id = "org_members"
        wos.user_management.send_invitation.return_value.role_slug = "viewer"
        monkeypatch.setattr(members, "_workos_client", lambda: wos)
        client = _client_as(permissions=["member:manage"])

        resp = client.post(
            f"{MEMBERS_PATH}/invitations",
            json={"email": "new@example.com", "role": "viewer"},
        )

        assert resp.status_code == 201, resp.text
        assert resp.json() == {
            "id": "inv_123",
            "email": "new@example.com",
            "organization_id": "org_members",
            "role": "viewer",
        }
        wos.user_management.send_invitation.assert_called_once_with(
            email="new@example.com",
            organization_id="org_members",
            role_slug="viewer",
            inviter_user_id="user_admin",
        )
    finally:
        _clear_overrides()


def test_member_invite_defaults_to_member_role(monkeypatch) -> None:
    import app.api.endpoints.members as members

    try:
        monkeypatch.setattr(settings, "WORKOS_API_KEY", "dummy-key")
        wos = MagicMock()
        wos.user_management.send_invitation.return_value.id = "inv_456"
        wos.user_management.send_invitation.return_value.email = "new@example.com"
        wos.user_management.send_invitation.return_value.organization_id = "org_members"
        wos.user_management.send_invitation.return_value.role_slug = "member"
        monkeypatch.setattr(members, "_workos_client", lambda: wos)
        client = _client_as(permissions=["member:manage"])

        resp = client.post(
            f"{MEMBERS_PATH}/invitations",
            json={"email": "new@example.com"},
        )

        assert resp.status_code == 201, resp.text
        wos.user_management.send_invitation.assert_called_once_with(
            email="new@example.com",
            organization_id="org_members",
            role_slug="member",
            inviter_user_id="user_admin",
        )
    finally:
        _clear_overrides()


def test_member_role_update_changes_membership_role(monkeypatch) -> None:
    import app.api.endpoints.members as members

    try:
        monkeypatch.setattr(settings, "WORKOS_API_KEY", "dummy-key")
        wos = MagicMock()
        wos.organization_membership.list_organization_memberships.return_value.data = [
            _membership("om_admin", "user_admin", "admin"),
            _membership("om_member", "user_member", "member"),
        ]
        wos.organization_membership.update_organization_membership.return_value = (
            _membership("om_member", "user_member", "admin")
        )
        monkeypatch.setattr(members, "_workos_client", lambda: wos)
        client = _client_as(permissions=["member:manage"])

        resp = client.patch(f"{MEMBERS_PATH}/om_member", json={"role": "admin"})

        assert resp.status_code == 200, resp.text
        assert resp.json()["role"] == "admin"
        wos.organization_membership.update_organization_membership.assert_called_once_with(
            "om_member", role="admin"
        )
    finally:
        _clear_overrides()


def test_member_role_update_rejects_demoting_last_admin(monkeypatch) -> None:
    import app.api.endpoints.members as members

    try:
        monkeypatch.setattr(settings, "WORKOS_API_KEY", "dummy-key")
        wos = MagicMock()
        wos.organization_membership.list_organization_memberships.return_value.data = [
            _membership("om_admin", "user_admin", "admin"),
            _membership("om_member", "user_member", "member"),
        ]
        monkeypatch.setattr(members, "_workos_client", lambda: wos)
        client = _client_as(permissions=["member:manage"])

        resp = client.patch(f"{MEMBERS_PATH}/om_admin", json={"role": "member"})

        assert resp.status_code == 409
        wos.organization_membership.update_organization_membership.assert_not_called()
    finally:
        _clear_overrides()


def test_member_remove_deletes_membership(monkeypatch) -> None:
    import app.api.endpoints.members as members

    try:
        monkeypatch.setattr(settings, "WORKOS_API_KEY", "dummy-key")
        wos = MagicMock()
        wos.organization_membership.list_organization_memberships.return_value.data = [
            _membership("om_admin", "user_admin", "admin"),
            _membership("om_member", "user_member", "member"),
        ]
        monkeypatch.setattr(members, "_workos_client", lambda: wos)
        client = _client_as(permissions=["member:manage"])

        resp = client.delete(f"{MEMBERS_PATH}/om_member")

        assert resp.status_code == 200, resp.text
        assert resp.json() == {"message": "Member removed successfully"}
        wos.organization_membership.delete_organization_membership.assert_called_once_with(
            "om_member"
        )
    finally:
        _clear_overrides()


def test_member_remove_rejects_removing_last_admin(monkeypatch) -> None:
    import app.api.endpoints.members as members

    try:
        monkeypatch.setattr(settings, "WORKOS_API_KEY", "dummy-key")
        wos = MagicMock()
        wos.organization_membership.list_organization_memberships.return_value.data = [
            _membership("om_admin", "user_admin", "admin"),
            _membership("om_member", "user_member", "member"),
        ]
        monkeypatch.setattr(members, "_workos_client", lambda: wos)
        client = _client_as(permissions=["member:manage"])

        resp = client.delete(f"{MEMBERS_PATH}/om_admin")

        assert resp.status_code == 409
        wos.organization_membership.delete_organization_membership.assert_not_called()
    finally:
        _clear_overrides()


def test_member_remove_allows_self_removal_when_another_admin_remains(
    monkeypatch,
) -> None:
    import app.api.endpoints.members as members

    try:
        monkeypatch.setattr(settings, "WORKOS_API_KEY", "dummy-key")
        wos = MagicMock()
        wos.organization_membership.list_organization_memberships.return_value.data = [
            _membership("om_admin_self", "user_admin", "admin"),
            _membership("om_admin_other", "user_other", "admin"),
        ]
        monkeypatch.setattr(members, "_workos_client", lambda: wos)
        client = _client_as(user_id="user_admin", permissions=["member:manage"])

        resp = client.delete(f"{MEMBERS_PATH}/om_admin_self")

        assert resp.status_code == 200, resp.text
        wos.organization_membership.delete_organization_membership.assert_called_once_with(
            "om_admin_self"
        )
    finally:
        _clear_overrides()


def test_member_endpoints_require_member_manage(monkeypatch) -> None:
    import app.api.endpoints.members as members

    try:
        monkeypatch.setattr(settings, "WORKOS_API_KEY", "dummy-key")
        monkeypatch.setattr(members, "_workos_client", lambda: MagicMock())
        client = _client_as(permissions=[])

        assert client.get(MEMBERS_PATH).status_code == 403
        assert (
            client.post(
                f"{MEMBERS_PATH}/invitations",
                json={"email": "new@example.com"},
            ).status_code
            == 403
        )
        assert (
            client.patch(f"{MEMBERS_PATH}/om_member", json={"role": "admin"}).status_code
            == 403
        )
        assert client.delete(f"{MEMBERS_PATH}/om_member").status_code == 403
    finally:
        _clear_overrides()
