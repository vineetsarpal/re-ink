"""
Tests for the WorkOS widget-token endpoint (app.api.endpoints.widgets).

The endpoint mints a short-lived WorkOS *widget session token* for the signed-in
user so the frontend User Profile widget can authenticate. These tests exercise
the endpoint through the FastAPI app: auth gating, the success path (with the
WorkOS client stubbed — no network), and the misconfiguration branches.
"""
import os
import sys
from pathlib import Path

# Configure environment before importing application modules
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_widgets.db")
os.environ.setdefault("LANDINGAI_API_KEY", "dummy-key")

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.core.auth import CurrentUser, get_current_user  # noqa: E402

TOKEN_PATH = "/api/widgets/user-profile/token"


def test_token_endpoint_requires_auth():
    """Without a Bearer token the endpoint is rejected with 401."""
    client = TestClient(app)
    resp = client.post(TOKEN_PATH)
    assert resp.status_code == 401


@pytest.fixture
def as_user():
    """Authenticate requests as a given CurrentUser via dependency override."""

    def _override(**kwargs):
        kwargs.setdefault("org_id", "org_01H")
        user = CurrentUser(user_id="user_01H", **kwargs)
        app.dependency_overrides[get_current_user] = lambda: user
        return user

    yield _override
    app.dependency_overrides.pop(get_current_user, None)


class _FakeWidgets:
    def __init__(self, recorder):
        self._recorder = recorder

    def create_token(self, **kwargs):
        self._recorder.update(kwargs)
        return type("Resp", (), {"token": "widget-token-xyz"})()


def test_mints_token_for_current_user(monkeypatch, as_user):
    """The endpoint returns a widget token scoped to the caller's org + user."""
    from app.api.endpoints import widgets as widgets_module

    monkeypatch.setattr(widgets_module.settings, "WORKOS_API_KEY", "sk_test", raising=False)
    recorder: dict = {}
    monkeypatch.setattr(
        widgets_module,
        "_workos_client",
        lambda: type("C", (), {"widgets": _FakeWidgets(recorder)})(),
    )

    as_user()
    client = TestClient(app)
    resp = client.post(TOKEN_PATH)

    assert resp.status_code == 200
    assert resp.json() == {"token": "widget-token-xyz"}
    # Token is scoped to the authenticated identity; User Profile needs no scope.
    assert recorder["organization_id"] == "org_01H"
    assert recorder["user_id"] == "user_01H"
    assert recorder["scopes"] is None


def test_user_without_org_is_conflict(monkeypatch, as_user):
    """A user with no organization can't be scoped — surface a clear 409."""
    from app.api.endpoints import widgets as widgets_module

    monkeypatch.setattr(widgets_module.settings, "WORKOS_API_KEY", "sk_test", raising=False)
    as_user(org_id=None)
    client = TestClient(app)
    resp = client.post(TOKEN_PATH)

    assert resp.status_code == 409


def test_missing_api_key_is_server_error(monkeypatch, as_user):
    """Without WORKOS_API_KEY the server can't mint tokens — 500, not a crash."""
    from app.api.endpoints import widgets as widgets_module

    monkeypatch.setattr(widgets_module.settings, "WORKOS_API_KEY", "", raising=False)
    as_user()
    client = TestClient(app)
    resp = client.post(TOKEN_PATH)

    assert resp.status_code == 500
