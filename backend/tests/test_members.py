"""
Organization member-management endpoints.

WorkOS is stubbed at the API boundary; tests exercise FastAPI behavior,
permission checks, WorkOS call arguments, and last-admin guards without network.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from fastapi.testclient import TestClient

from app.core.auth import CurrentUser, get_current_user
from app.core.config import settings
from app.db.database import get_db
from app.main import app

MEMBERS_PATH = "/api/members"


def _clear_overrides() -> None:
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_db, None)


def _client_as(
    *,
    user_id: str = "user_admin",
    permissions: list[str],
    db=None,
    raise_server_exceptions: bool = True,
) -> TestClient:
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user_id=user_id,
        org_id="org_members",
        role="admin",
        permissions=permissions,
    )
    if db is not None:
        def _get_test_db():
            yield db

        app.dependency_overrides[get_db] = _get_test_db
    return TestClient(app, raise_server_exceptions=raise_server_exceptions)


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


def _leave_wos(org_pages, user_pages):
    """WorkOS fake for leave: org-scoped and user-scoped listings, keyed by cursor."""
    def to_page(data, after):
        page = MagicMock()
        page.data = data
        page.after = after
        return page

    def list_memberships(**kwargs):
        pages = org_pages if "organization_id" in kwargs else user_pages
        if "user_id" in kwargs:
            assert kwargs["statuses"] == ["active", "inactive", "pending"]
        index = 0 if kwargs.get("after") is None else int(kwargs["after"])
        after = str(index + 1) if index + 1 < len(pages) else None
        return to_page(pages[index], after)

    wos = MagicMock()
    wos.organization_membership.list_organization_memberships.side_effect = (
        list_memberships
    )
    return wos


def _add_intent(session, intent_id: str, user_id: str = "user_member") -> None:
    from app.models.provisioning_intent import ProvisioningIntent

    session.add(
        ProvisioningIntent(
            user_id=user_id,
            intent_id=intent_id,
            state="completed",
            org_id="org_members",
        )
    )


def _intent_exists(session, user_id: str = "user_member") -> bool:
    from app.models.provisioning_intent import ProvisioningIntent

    return session.get(ProvisioningIntent, user_id, populate_existing=True) is not None


def test_member_leave_rejects_last_admin_with_actionable_message(
    monkeypatch, restricted_engine
) -> None:
    import app.api.endpoints.members as members
    from sqlalchemy.orm import Session
    from app.models.provisioning_intent import ProvisioningIntent

    own = _membership("om_admin", "user_admin", "admin")
    try:
        monkeypatch.setattr(settings, "WORKOS_API_KEY", "dummy-key")
        wos = _leave_wos(
            [[own, _membership("om_member", "user_member", "member")]],
            [[own]],
        )
        monkeypatch.setattr(members, "_workos_client", lambda: wos)
        with Session(restricted_engine) as session:
            _add_intent(session, "intent_leave_last_admin", user_id="user_admin")
            session.commit()

        def _get_request_db():
            with Session(restricted_engine) as session:
                yield session

        client = _client_as(permissions=[])
        app.dependency_overrides[get_db] = _get_request_db

        resp = client.post(f"{MEMBERS_PATH}/me/leave")

        assert resp.status_code == 409
        assert resp.json()["detail"] == (
            "Cannot remove or demote the last admin. Promote another member to "
            "admin or close the organization first."
        )
        wos.organization_membership.delete_organization_membership.assert_not_called()
        wos.user_management.delete_user.assert_not_called()
        with Session(restricted_engine) as session:
            assert session.get(ProvisioningIntent, "user_admin") is not None
    finally:
        _clear_overrides()
        with Session(restricted_engine) as session:
            intent = session.get(ProvisioningIntent, "user_admin")
            if intent is not None:
                session.delete(intent)
                session.commit()


def test_member_leave_removes_membership_and_keeps_account_with_other_memberships(
    monkeypatch, db_session
) -> None:
    import app.api.endpoints.members as members

    own = _membership("om_member", "user_member", "member")
    other_org = _membership("om_other_org", "user_member", "member")
    other_org.organization_id = "org_other"
    other_admin = _membership("om_admin", "user_admin", "admin")

    try:
        monkeypatch.setattr(settings, "WORKOS_API_KEY", "dummy-key")
        wos = _leave_wos([[own, other_admin]], [[own, other_org]])
        monkeypatch.setattr(members, "_workos_client", lambda: wos)
        _add_intent(db_session, "intent_leave_other_org")
        db_session.flush()
        client = _client_as(user_id="user_member", permissions=[], db=db_session)

        resp = client.post(f"{MEMBERS_PATH}/me/leave")

        assert resp.status_code == 200, resp.text
        assert resp.json() == {"account_deleted": False}
        wos.organization_membership.delete_organization_membership.assert_called_once_with(
            "om_member"
        )
        wos.user_management.delete_user.assert_not_called()
        assert _intent_exists(db_session)
    finally:
        _clear_overrides()


def test_member_leave_finds_membership_and_other_admin_on_later_page(
    monkeypatch, db_session
) -> None:
    import app.api.endpoints.members as members

    own = _membership("om_admin", "user_admin", "admin")
    org_pages = [
        [
            _membership(f"om_other_{index}", f"user_other_{index}", "member")
            for index in range(10)
        ],
        [own, _membership("om_other_admin", "user_other_admin", "admin")],
    ]
    other_org = _membership("om_other_org", "user_admin", "member")
    other_org.organization_id = "org_other"

    try:
        monkeypatch.setattr(settings, "WORKOS_API_KEY", "dummy-key")
        wos = _leave_wos(org_pages, [[own, other_org]])
        monkeypatch.setattr(members, "_workos_client", lambda: wos)
        client = _client_as(permissions=[], db=db_session)

        resp = client.post(f"{MEMBERS_PATH}/me/leave")

        assert resp.status_code == 200, resp.text
        assert resp.json() == {"account_deleted": False}
        wos.organization_membership.delete_organization_membership.assert_called_once_with(
            "om_admin"
        )
        assert (
            wos.organization_membership.list_organization_memberships.call_args_list[1]
            .kwargs
            == {"organization_id": "org_members", "after": "1"}
        )
    finally:
        _clear_overrides()


def test_member_leave_finds_other_membership_on_later_user_page(
    monkeypatch, db_session
) -> None:
    import app.api.endpoints.members as members

    own = _membership("om_member", "user_member", "member")
    other_admin = _membership("om_admin", "user_admin", "admin")
    other_org = _membership("om_other_org", "user_member", "member")
    other_org.organization_id = "org_other"

    try:
        monkeypatch.setattr(settings, "WORKOS_API_KEY", "dummy-key")
        wos = _leave_wos([[own, other_admin]], [[own], [other_org]])
        monkeypatch.setattr(members, "_workos_client", lambda: wos)
        client = _client_as(user_id="user_member", permissions=[], db=db_session)

        resp = client.post(f"{MEMBERS_PATH}/me/leave")

        assert resp.status_code == 200, resp.text
        assert resp.json() == {"account_deleted": False}
        wos.organization_membership.delete_organization_membership.assert_called_once_with(
            "om_member"
        )
        wos.user_management.delete_user.assert_not_called()
    finally:
        _clear_overrides()


def test_member_leave_keeps_account_with_non_active_memberships(
    monkeypatch, db_session
) -> None:
    import app.api.endpoints.members as members

    own = _membership("om_member", "user_member", "member")
    other_admin = _membership("om_admin", "user_admin", "admin")
    pending = _membership("om_pending", "user_member", "member")
    pending.organization_id = "org_pending"

    try:
        monkeypatch.setattr(settings, "WORKOS_API_KEY", "dummy-key")
        wos = _leave_wos([[own, other_admin]], [[own, pending]])
        monkeypatch.setattr(members, "_workos_client", lambda: wos)
        client = _client_as(user_id="user_member", permissions=[], db=db_session)

        resp = client.post(f"{MEMBERS_PATH}/me/leave")

        assert resp.status_code == 200, resp.text
        assert resp.json() == {"account_deleted": False}
        wos.user_management.delete_user.assert_not_called()
    finally:
        _clear_overrides()


def test_member_leave_deletes_account_and_intent_at_zero_memberships(
    monkeypatch, db_session
) -> None:
    import app.api.endpoints.members as members

    own = _membership("om_member", "user_member", "member")
    other_admin = _membership("om_admin", "user_admin", "admin")

    try:
        monkeypatch.setattr(settings, "WORKOS_API_KEY", "dummy-key")
        wos = _leave_wos([[own, other_admin]], [[own]])
        monkeypatch.setattr(members, "_workos_client", lambda: wos)
        _add_intent(db_session, "intent_leave_last_org")
        db_session.flush()
        client = _client_as(user_id="user_member", permissions=[], db=db_session)

        resp = client.post(f"{MEMBERS_PATH}/me/leave")

        assert resp.status_code == 200, resp.text
        assert resp.json() == {"account_deleted": True}
        wos.user_management.delete_user.assert_called_once_with("user_member")
        wos.organization_membership.delete_organization_membership.assert_not_called()
        assert not _intent_exists(db_session)
    finally:
        _clear_overrides()


def test_member_leave_workos_user_delete_failure_mutates_nothing(
    monkeypatch, restricted_engine
) -> None:
    import app.api.endpoints.members as members
    from sqlalchemy.orm import Session
    from app.models.provisioning_intent import ProvisioningIntent

    own = _membership("om_member", "user_member", "member")
    other_admin = _membership("om_admin", "user_admin", "admin")

    try:
        monkeypatch.setattr(settings, "WORKOS_API_KEY", "dummy-key")
        wos = _leave_wos([[own, other_admin]], [[own]])
        wos.user_management.delete_user.side_effect = RuntimeError("WorkOS unavailable")
        monkeypatch.setattr(members, "_workos_client", lambda: wos)
        with Session(restricted_engine) as session:
            _add_intent(session, "intent_leave_delete_failure")
            session.commit()

        def _get_request_db():
            with Session(restricted_engine) as session:
                yield session

        client = _client_as(
            user_id="user_member",
            permissions=[],
            raise_server_exceptions=False,
        )
        app.dependency_overrides[get_db] = _get_request_db

        resp = client.post(f"{MEMBERS_PATH}/me/leave")

        assert resp.status_code == 500
        wos.user_management.delete_user.assert_called_once_with("user_member")
        wos.organization_membership.delete_organization_membership.assert_not_called()
        with Session(restricted_engine) as session:
            assert session.get(ProvisioningIntent, "user_member") is not None
    finally:
        _clear_overrides()
        with Session(restricted_engine) as session:
            intent = session.get(ProvisioningIntent, "user_member")
            if intent is not None:
                session.delete(intent)
                session.commit()


def test_member_leave_holds_org_advisory_lock_while_mutating(
    monkeypatch, db_session, restricted_engine
) -> None:
    import app.api.endpoints.members as members
    from sqlalchemy import text

    own = _membership("om_member", "user_member", "member")
    other_admin = _membership("om_admin", "user_admin", "admin")
    lock_free_during_delete = []

    def delete_membership(membership_id):
        with restricted_engine.connect() as other:
            lock_free_during_delete.append(
                other.execute(
                    text(
                        "SELECT pg_try_advisory_xact_lock("
                        "hashtextextended(:key, 0))"
                    ),
                    {"key": "reink:org-membership:org_members"},
                ).scalar()
            )
            other.rollback()

    try:
        monkeypatch.setattr(settings, "WORKOS_API_KEY", "dummy-key")
        other_org = _membership("om_other_org", "user_member", "member")
        wos = _leave_wos([[own, other_admin]], [[own, other_org]])
        wos.organization_membership.delete_organization_membership.side_effect = (
            delete_membership
        )
        monkeypatch.setattr(members, "_workos_client", lambda: wos)
        client = _client_as(user_id="user_member", permissions=[], db=db_session)

        resp = client.post(f"{MEMBERS_PATH}/me/leave")

        assert resp.status_code == 200, resp.text
        assert lock_free_during_delete == [False]
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


@pytest.mark.parametrize("action", ["remove", "demote"])
def test_admin_membership_changes_hold_org_advisory_lock(
    monkeypatch, db_session, restricted_engine, action
) -> None:
    import app.api.endpoints.members as members
    from sqlalchemy import text

    target = _membership("om_target", "user_target", "admin")
    me = _membership("om_admin", "user_admin", "admin")
    lock_free_during_mutation = []

    def probe_lock(*_args, **_kwargs):
        with restricted_engine.connect() as other:
            lock_free_during_mutation.append(other.execute(
                text("SELECT pg_try_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": "reink:org-membership:org_members"},
            ).scalar())
            other.rollback()
        return target

    try:
        monkeypatch.setattr(settings, "WORKOS_API_KEY", "dummy-key")
        wos = MagicMock()
        page = MagicMock()
        page.data = [target, me]
        page.after = None
        wos.organization_membership.list_organization_memberships.return_value = page
        wos.organization_membership.delete_organization_membership.side_effect = probe_lock
        wos.organization_membership.update_organization_membership.side_effect = probe_lock
        monkeypatch.setattr(members, "_workos_client", lambda: wos)
        client = _client_as(permissions=["member:manage"], db=db_session)

        if action == "remove":
            resp = client.delete(f"{MEMBERS_PATH}/om_target")
        else:
            resp = client.patch(f"{MEMBERS_PATH}/om_target", json={"role": "viewer"})

        assert resp.status_code == 200, resp.text
        assert lock_free_during_mutation == [False]
    finally:
        _clear_overrides()
