"""Synthetic trial access is restricted to explicitly selected organizations."""
import pytest

from app.core.config import settings


@pytest.mark.parametrize(("method", "path", "kwargs"), [
    ("get", "/api/provider-credentials/landingai", {}),
    ("put", "/api/provider-credentials/landingai", {"json": {"api_key": "key"}}),
    ("delete", "/api/provider-credentials/landingai", {}),
    ("get", "/api/provider-credentials/landingai/acknowledgment", {}),
    ("post", "/api/provider-credentials/landingai/acknowledgment", {}),
    ("get", "/api/documents/usage", {}),
    ("post", "/api/documents/missing/retry", {}),
    ("post", "/api/documents/upload", {"data": {"api_key": "key"}, "files": {"file": ("test.pdf", b"fake", "application/pdf")}}),
])
def test_unselected_org_cannot_access_trial_even_with_legacy_key(as_org, monkeypatch, method, path, kwargs):
    monkeypatch.setattr(settings, "CLOUDFLARE_TRIAL_ENABLED", True)
    monkeypatch.setattr(settings, "TRIAL_ALLOWED_ORGANIZATION_IDS", ["selected-org"], raising=False)
    response = getattr(as_org("other-org"), method)(path, **kwargs)
    assert response.status_code == 503


def test_config_and_access_follow_authenticated_org_and_revocation(as_org, monkeypatch):
    monkeypatch.setattr(settings, "CLOUDFLARE_TRIAL_ENABLED", True)
    monkeypatch.setattr(settings, "TRIAL_ALLOWED_ORGANIZATION_IDS", [], raising=False)
    client = as_org("selected-org")
    assert client.get("/api/system/config").json()["provider_credentials_enabled"] is False
    assert client.get("/api/system/config").json()["trial_routing_enabled"] is True
    assert client.get("/api/provider-credentials/landingai").status_code == 503
    monkeypatch.setattr(settings, "TRIAL_ALLOWED_ORGANIZATION_IDS", ["selected-org"])
    assert client.get("/api/system/config").json()["provider_credentials_enabled"] is True
    assert client.get("/api/provider-credentials/landingai").status_code == 200
    monkeypatch.setattr(settings, "TRIAL_ALLOWED_ORGANIZATION_IDS", [])
    assert client.get("/api/provider-credentials/landingai").status_code == 503


def test_allowlisted_org_still_requires_permissions(as_org, monkeypatch):
    from app.core.auth import CurrentUser, get_current_user
    from app.main import app

    monkeypatch.setattr(settings, "CLOUDFLARE_TRIAL_ENABLED", True)
    monkeypatch.setattr(settings, "TRIAL_ALLOWED_ORGANIZATION_IDS", ["selected-org"])
    client = as_org("selected-org")
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user_id="viewer", org_id="selected-org", permissions=[]
    )
    assert client.get("/api/provider-credentials/landingai").status_code == 403
    assert client.post("/api/provider-credentials/landingai/acknowledgment").status_code == 403
    assert client.get("/api/documents/usage").status_code == 403
    assert client.post("/api/documents/missing/retry").status_code == 403
    assert client.post("/api/documents/upload", files={"file": ("test.pdf", b"fake", "application/pdf")}).status_code == 403


def test_trial_switch_disables_allowlisted_org(as_org, monkeypatch):
    monkeypatch.setattr(settings, "CLOUDFLARE_TRIAL_ENABLED", False)
    monkeypatch.setattr(settings, "TRIAL_ALLOWED_ORGANIZATION_IDS", ["selected-org"])
    client = as_org("selected-org")
    assert client.get("/api/system/config").json()["provider_credentials_enabled"] is False
    assert client.get("/api/system/config").json()["trial_routing_enabled"] is False
    assert client.get("/api/provider-credentials/landingai").status_code == 503
