"""
Permission enforcement tests at the identity seam.

These tests inject ``CurrentUser`` directly via FastAPI dependency overrides, so
they exercise endpoint behavior without minting real WorkOS JWTs.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.auth import CurrentUser, get_current_user
from app.core.tenancy import bind_session_to_org, get_tenant_db
from app.main import app


ORG_ID = "org_permission_test"


def _clear_overrides() -> None:
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_tenant_db, None)


def _client_as(db_session, *, role: str, permissions: list[str]) -> TestClient:
    _clear_overrides()
    bind_session_to_org(db_session, ORG_ID)
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user_id="test-user",
        org_id=ORG_ID,
        role=role,
        permissions=permissions,
    )

    def _tenant_db():
        bind_session_to_org(db_session, ORG_ID)
        yield db_session

    app.dependency_overrides[get_tenant_db] = _tenant_db
    return TestClient(app)


def _contract_payload(number: str) -> dict:
    return {
        "contract_number": number,
        "contract_name": "Permission Probe",
        "effective_date": "2026-01-01",
        "expiration_date": "2026-12-31",
    }


def test_contract_delete_requires_contract_delete_permission(db_session) -> None:
    try:
        client = _client_as(db_session, role="admin", permissions=[])
        created = client.post("/api/contracts/", json=_contract_payload("PERM-1"))
        assert created.status_code == 201, created.text

        denied = client.delete(f"/api/contracts/{created.json()['id']}")

        assert denied.status_code == 403
    finally:
        _clear_overrides()


def test_contract_delete_allows_any_role_with_contract_delete_permission(
    db_session,
) -> None:
    try:
        client = _client_as(db_session, role="viewer", permissions=["contract.delete"])
        created = client.post("/api/contracts/", json=_contract_payload("PERM-2"))
        assert created.status_code == 201, created.text

        allowed = client.delete(f"/api/contracts/{created.json()['id']}")

        assert allowed.status_code == 200
        assert allowed.json() == {"message": "Contract deleted successfully"}
    finally:
        _clear_overrides()
