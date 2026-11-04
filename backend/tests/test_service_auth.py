"""Machine authentication, transaction scope and fail-closed configuration."""
import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import ValidationError
from sqlalchemy import text

from app.core.auth import CurrentUser, get_current_user
from app.core.config import Settings, settings
from app.core import service_auth


def configured(monkeypatch):
    for name, value in {
        "WORKFLOW_CUSTOMER_ORG_ID": "org_workflow",
        "WORKFLOW_WEBHOOK_URL": "https://n8n.example.invalid/webhook/reink-extraction-v1",
        "WORKFLOW_DISPATCH_TOKEN": "d" * 32,
        "WORKFLOW_SERVICE_TOKEN": "s" * 32,
    }.items():
        monkeypatch.setattr(settings, name, value)


def test_service_auth_fails_closed_and_rejects_dispatch_token(monkeypatch):
    monkeypatch.setattr(settings, "WORKFLOW_SERVICE_TOKEN", "")
    with pytest.raises(HTTPException) as exc:
        service_auth.require_workflow_service(None)
    assert exc.value.status_code == 503
    configured(monkeypatch)
    for token in (None, "d" * 32, "wrong", "s" * 31):
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token) if token else None
        with pytest.raises(HTTPException) as exc:
            service_auth.require_workflow_service(credentials)
        assert exc.value.status_code == 401
    identity = service_auth.require_workflow_service(HTTPAuthorizationCredentials(scheme="Bearer", credentials="s" * 32))
    assert identity.org_id == "org_workflow"
    assert not hasattr(identity, "permissions")


def test_customer_browser_scope(monkeypatch):
    configured(monkeypatch)
    assert get_current_user(CurrentUser(user_id="u", org_id="org_workflow")).org_id == "org_workflow"
    with pytest.raises(HTTPException) as exc:
        get_current_user(CurrentUser(user_id="u", org_id="another"))
    assert exc.value.status_code == 403


@pytest.mark.parametrize("overrides", [
    {"WORKFLOW_SERVICE_TOKEN": "short"},
    {"WORKFLOW_SERVICE_TOKEN": "x" * 32, "WORKFLOW_DISPATCH_TOKEN": "x" * 32},
    {"WORKFLOW_WEBHOOK_URL": "http://n8n.example.invalid/webhook"},
    {"WORKFLOW_WEBHOOK_URL": "https://user:secret@n8n.example.invalid/webhook"},
    {"R2_ENDPOINT_URL": "http://storage.example.invalid"},
    {"WORKFLOW_HTTP_TIMEOUT_SECONDS": 60},
    {"WORKFLOW_UPLOADS_ENABLED": True, "WORKFLOW_SERVICE_TOKEN": ""},
])
def test_unsafe_configuration_rejected(overrides):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, DATABASE_URL="postgresql://localhost/test", **overrides)


def test_worker_requires_verified_tls():
    service_auth.validate_worker_database_url("postgresql://worker:secret@db.example.invalid/db?sslmode=verify-full")
    for url in ("", "postgresql://worker@localhost/db", "postgresql://worker@db.example.invalid/db?sslmode=require"):
        with pytest.raises(ValueError):
            service_auth.validate_worker_database_url(url)


def test_machine_db_rebinds_customer_after_commit(monkeypatch, restricted_engine):
    from sqlalchemy.orm import sessionmaker
    monkeypatch.setattr(service_auth, "SessionLocal", sessionmaker(bind=restricted_engine))
    dependency = service_auth.get_workflow_db(service_auth.WorkflowServiceIdentity("org_workflow"))
    session = next(dependency)
    try:
        for _ in range(2):
            assert session.scalar(text("SELECT current_setting('app.current_org', true)")) == "org_workflow"
            session.commit()
    finally:
        dependency.close()
