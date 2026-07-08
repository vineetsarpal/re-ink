"""
Admin Portal link endpoint.

The WorkOS client is stubbed at the API boundary; tests exercise the FastAPI
endpoint, permission gate, and intent passthrough without network calls.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.core.auth import CurrentUser, get_current_user
from app.core.config import settings
from app.main import app

PORTAL_LINK_PATH = "/api/admin/portal-link"


def _client_as(*, permissions: list[str]) -> TestClient:
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user_id="user_admin",
        org_id="org_admin",
        role="admin",
        permissions=permissions,
    )
    return TestClient(app)


def _clear_overrides() -> None:
    app.dependency_overrides.pop(get_current_user, None)


def test_admin_portal_link_requires_sso_manage(monkeypatch) -> None:
    try:
        monkeypatch.setattr(settings, "WORKOS_API_KEY", "dummy-key")
        client = _client_as(permissions=[])

        resp = client.post(PORTAL_LINK_PATH, json={"intent": "sso"})

        assert resp.status_code == 403
    finally:
        _clear_overrides()


@pytest.mark.parametrize("intent", ["sso", "dsync", "domain_verification"])
def test_admin_portal_link_passes_intent_to_workos(monkeypatch, intent: str) -> None:
    import app.api.endpoints.admin as admin

    try:
        monkeypatch.setattr(settings, "WORKOS_API_KEY", "dummy-key")
        wos = MagicMock()
        wos.admin_portal.generate_link.return_value.link = (
            f"https://workos.test/admin/{intent}"
        )
        monkeypatch.setattr(admin, "_workos_client", lambda: wos)
        client = _client_as(permissions=["sso.manage"])

        resp = client.post(PORTAL_LINK_PATH, json={"intent": intent})

        assert resp.status_code == 200, resp.text
        assert resp.json() == {"url": f"https://workos.test/admin/{intent}"}
        wos.admin_portal.generate_link.assert_called_once_with(
            organization="org_admin",
            intent=intent,
        )
    finally:
        _clear_overrides()
