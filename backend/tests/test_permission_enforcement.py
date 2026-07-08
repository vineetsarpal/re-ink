"""
Permission enforcement tests at the identity seam.

These tests inject ``CurrentUser`` directly via FastAPI dependency overrides, so
they exercise endpoint behavior without minting real WorkOS JWTs.
"""
from __future__ import annotations

from io import BytesIO

import pytest
from fastapi.testclient import TestClient

from app.core.auth import CurrentUser, get_current_user
from app.core.tenancy import bind_session_to_org, get_tenant_db
from app.main import app


ORG_ID = "org_permission_test"
VIEWER_PERMISSIONS = ["contract.read", "party.read"]
MEMBER_PERMISSIONS = [
    *VIEWER_PERMISSIONS,
    "contract.write",
    "party.write",
    "document.upload",
    "review.approve",
]
ADMIN_PERMISSIONS = [
    *MEMBER_PERMISSIONS,
    "contract.delete",
    "party.delete",
    "member.manage",
    "sso.manage",
]


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


def _party_payload(name: str) -> dict:
    return {"name": name}


def _review_payload(number: str) -> dict:
    return {
        "contract": _contract_payload(number),
        "parties": [
            {
                "action": "create_new",
                "role": "cedant",
                "party_data": _party_payload(f"{number} Cedant"),
            }
        ],
    }


def test_contract_create_requires_contract_write_permission(db_session) -> None:
    try:
        client = _client_as(
            db_session, role="viewer", permissions=["contract.read"]
        )

        denied = client.post("/api/contracts/", json=_contract_payload("PERM-WRITE"))

        assert denied.status_code == 403
    finally:
        _clear_overrides()


def test_contract_list_requires_contract_read_permission(db_session) -> None:
    try:
        writer = _client_as(
            db_session, role="member", permissions=["contract.write"]
        )
        created = writer.post("/api/contracts/", json=_contract_payload("PERM-READ"))
        assert created.status_code == 201, created.text

        no_read = _client_as(db_session, role="member", permissions=["contract.write"])
        denied = no_read.get("/api/contracts/")

        assert denied.status_code == 403
    finally:
        _clear_overrides()


def test_party_create_requires_party_write_permission(db_session) -> None:
    try:
        client = _client_as(db_session, role="viewer", permissions=["party.read"])

        denied = client.post("/api/parties/", json=_party_payload("Read Only Cedant"))

        assert denied.status_code == 403
    finally:
        _clear_overrides()


def test_document_upload_requires_document_upload_permission(db_session) -> None:
    try:
        client = _client_as(
            db_session, role="viewer", permissions=["contract.read", "party.read"]
        )

        denied = client.post(
            "/api/documents/upload",
            files={"file": ("contract.pdf", BytesIO(b"%PDF-1.4"), "application/pdf")},
        )

        assert denied.status_code == 403
    finally:
        _clear_overrides()


def test_review_approve_requires_review_approve_permission(db_session) -> None:
    try:
        client = _client_as(
            db_session,
            role="viewer",
            permissions=["contract.read", "party.read"],
        )

        denied = client.post("/api/review/approve", json=_review_payload("PERM-APPROVE"))

        assert denied.status_code == 403
    finally:
        _clear_overrides()


def test_automated_review_agent_requires_contract_read_permission(db_session) -> None:
    try:
        client = _client_as(db_session, role="member", permissions=["contract.write"])

        denied = client.post(
            "/api/agents/review",
            json={"contract_id": 12345, "user_input": "Review this contract."},
        )

        assert denied.status_code == 403
    finally:
        _clear_overrides()


@pytest.mark.parametrize(
    ("method", "path", "kwargs"),
    [
        ("get", "/api/contracts/12345", {}),
        ("put", "/api/contracts/12345", {"json": {"contract_name": "Updated"}}),
        ("post", "/api/contracts/12345/parties/67890?role=cedant", {}),
        ("patch", "/api/contracts/12345/parties/67890?role=reinsurer", {}),
        ("delete", "/api/contracts/12345/parties/67890", {}),
        ("get", "/api/parties/12345", {}),
        ("get", "/api/parties/search/by-name?name=cedant", {}),
        ("post", "/api/parties/match", {"json": {"names": ["Cedant Co"]}}),
        ("put", "/api/parties/12345", {"json": {"name": "Updated Party"}}),
        ("delete", "/api/parties/12345", {}),
        ("post", "/api/documents/mock-job", {"json": {"job_id": "forbidden-job"}}),
        ("delete", "/api/documents/forbidden-job", {}),
        ("post", "/api/review/reject/forbidden-job?reason=bad", {}),
        (
            "post",
            "/api/agents/intake",
            {"json": {"job_id": "forbidden-job", "user_input": "Check it"}},
        ),
    ],
)
def test_resource_endpoints_fail_closed_when_permission_is_missing(
    db_session, method: str, path: str, kwargs: dict
) -> None:
    try:
        client = _client_as(db_session, role="viewer", permissions=[])

        denied = getattr(client, method)(path, **kwargs)

        assert denied.status_code == 403
    finally:
        _clear_overrides()


def test_role_permission_sets_match_resource_behavior(db_session) -> None:
    try:
        viewer = _client_as(db_session, role="viewer", permissions=VIEWER_PERMISSIONS)
        assert viewer.get("/api/contracts/").status_code == 200
        assert viewer.get("/api/parties/").status_code == 200
        assert viewer.get("/api/parties/search/by-name?name=cedant").status_code == 200
        assert viewer.post("/api/documents/mock-job", json={"job_id": "viewer-job"}).status_code == 403
        assert viewer.post("/api/review/approve", json=_review_payload("VIEWER-DENY")).status_code == 403

        member = _client_as(db_session, role="member", permissions=MEMBER_PERMISSIONS)
        party = member.post("/api/parties/", json=_party_payload("Member Cedant"))
        assert party.status_code == 201, party.text
        contract = member.post("/api/contracts/", json=_contract_payload("MEMBER-ALLOW"))
        assert contract.status_code == 201, contract.text
        job = member.post("/api/documents/mock-job", json={"job_id": "member-job"})
        assert job.status_code == 200, job.text
        approval = member.post("/api/review/approve", json=_review_payload("MEMBER-APPROVE"))
        assert approval.status_code == 200, approval.text
        assert member.delete(f"/api/contracts/{contract.json()['id']}").status_code == 403
        assert member.delete(f"/api/parties/{party.json()['id']}").status_code == 403

        admin = _client_as(db_session, role="admin", permissions=ADMIN_PERMISSIONS)
        assert admin.delete(f"/api/contracts/{contract.json()['id']}").status_code == 200
        assert admin.delete(f"/api/parties/{party.json()['id']}").status_code == 200
    finally:
        _clear_overrides()


def test_contract_delete_requires_contract_delete_permission(db_session) -> None:
    try:
        writer = _client_as(db_session, role="member", permissions=["contract.write"])
        created = writer.post("/api/contracts/", json=_contract_payload("PERM-1"))
        assert created.status_code == 201, created.text

        client = _client_as(db_session, role="admin", permissions=[])
        denied = client.delete(f"/api/contracts/{created.json()['id']}")

        assert denied.status_code == 403
    finally:
        _clear_overrides()


def test_contract_delete_allows_any_role_with_contract_delete_permission(
    db_session,
) -> None:
    try:
        writer = _client_as(db_session, role="member", permissions=["contract.write"])
        created = writer.post("/api/contracts/", json=_contract_payload("PERM-2"))
        assert created.status_code == 201, created.text

        client = _client_as(db_session, role="viewer", permissions=["contract.delete"])
        allowed = client.delete(f"/api/contracts/{created.json()['id']}")

        assert allowed.status_code == 200
        assert allowed.json() == {"message": "Contract deleted successfully"}
    finally:
        _clear_overrides()
