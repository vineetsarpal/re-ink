"""Tenant-admin API behavior for stored LandingAI keys."""

import base64
import uuid

from app.core.config import settings


def test_admin_can_save_replace_and_remove_key_without_disclosure(client, monkeypatch):
    from app.api.endpoints import provider_credentials
    monkeypatch.setattr(provider_credentials, "credentials_available", lambda user: True)
    monkeypatch.setattr(provider_credentials, "validate_landingai_key", lambda key: True)
    monkeypatch.setattr(settings, "PROVIDER_CREDENTIAL_ENCRYPTION_KEY", base64.urlsafe_b64encode(b"x" * 32).decode())
    path = "/api/provider-credentials/landingai"
    assert client.get(path).json() == {"configured": False}
    for value in ("first-key", "replacement-key"):
        response = client.put(path, json={"api_key": value})
        assert response.status_code == 200, response.text
        assert response.json() == {"configured": True}
        assert value not in response.text
    assert client.delete(path).status_code == 204
    assert client.get(path).json() == {"configured": False}


def test_key_settings_are_disabled_until_extraction_is_connected(client):
    assert client.get("/api/provider-credentials/landingai").status_code == 503


def test_keys_are_isolated_between_organizations(as_org, monkeypatch):
    from app.api.endpoints import provider_credentials
    monkeypatch.setattr(provider_credentials, "credentials_available", lambda user: True)
    monkeypatch.setattr(provider_credentials, "validate_landingai_key", lambda key: True)
    monkeypatch.setattr(settings, "PROVIDER_CREDENTIAL_ENCRYPTION_KEY", base64.urlsafe_b64encode(b"x" * 32).decode())
    path = "/api/provider-credentials/landingai"
    assert as_org("key-org-a").put(path, json={"api_key": "org-a-key"}).status_code == 200
    assert as_org("key-org-b").get(path).json() == {"configured": False}


def test_processing_acknowledgment_is_scoped_to_organization(as_org, monkeypatch):
    from app.api.endpoints import provider_credentials
    monkeypatch.setattr(provider_credentials, "credentials_available", lambda user: True)
    path = "/api/provider-credentials/landingai/acknowledgment"
    first = as_org("notice-org-a-" + uuid.uuid4().hex)
    assert first.get(path).json() == {"acknowledged": False}
    assert first.post(path).json() == {"acknowledged": True}
    assert first.get(path).json() == {"acknowledged": True}
    assert as_org("notice-org-b").get(path).json() == {"acknowledged": False}
