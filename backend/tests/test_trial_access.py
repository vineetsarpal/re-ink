"""Extraction access follows the trial switch and existing permissions."""
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
])
def test_disabled_trial_rejects_access_even_with_legacy_key(as_org, monkeypatch, method, path, kwargs):
    monkeypatch.setattr(settings, "CLOUDFLARE_TRIAL_ENABLED", False)
    response = getattr(as_org("other-org"), method)(path, **kwargs)
    assert response.status_code == 503


def test_config_and_access_follow_trial_switch(as_org, monkeypatch):
    monkeypatch.setattr(settings, "CLOUDFLARE_TRIAL_ENABLED", True)
    client = as_org("any-org")
    assert client.get("/api/system/config").json()["provider_credentials_enabled"] is True
    assert client.get("/api/system/config").json()["trial_routing_enabled"] is True
    assert client.get("/api/provider-credentials/landingai").status_code == 200
    monkeypatch.setattr(settings, "CLOUDFLARE_TRIAL_ENABLED", False)
    assert client.get("/api/system/config").json()["provider_credentials_enabled"] is False
    assert client.get("/api/provider-credentials/landingai").status_code == 503


def test_open_access_still_requires_permissions(as_org, monkeypatch):
    from app.core.auth import CurrentUser, get_current_user
    from app.main import app

    monkeypatch.setattr(settings, "CLOUDFLARE_TRIAL_ENABLED", True)
    client = as_org("selected-org")
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user_id="viewer", org_id="selected-org", permissions=[]
    )
    assert client.get("/api/provider-credentials/landingai").status_code == 403
    assert client.post("/api/provider-credentials/landingai/acknowledgment").status_code == 403
    assert client.get("/api/documents/usage").status_code == 403
    assert client.post("/api/documents/missing/retry").status_code == 403
    assert client.post("/api/documents/upload", files={"file": ("test.pdf", b"fake", "application/pdf")}).status_code == 403


def test_trial_switch_disables_org(as_org, monkeypatch):
    monkeypatch.setattr(settings, "CLOUDFLARE_TRIAL_ENABLED", False)
    client = as_org("selected-org")
    assert client.get("/api/system/config").json()["provider_credentials_enabled"] is False
    assert client.get("/api/system/config").json()["trial_routing_enabled"] is False
    assert client.get("/api/provider-credentials/landingai").status_code == 503
