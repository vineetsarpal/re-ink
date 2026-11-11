"""Public upload behavior for the optional trial path."""
import base64
import io
from uuid import uuid4
import pytest
from pydantic import ValidationError

from pypdf import PdfWriter

from app.core.config import settings


def test_incomplete_cloudflare_configuration_cannot_start():
    from app.core.config import Settings
    with pytest.raises(ValidationError):
        Settings(_env_file=None, DATABASE_URL="postgresql://app@localhost/db", CLOUDFLARE_ENABLED=True, EXTRACTION_QUOTA_ENABLED=True)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, DATABASE_URL="postgresql://app@localhost/db", CLOUDFLARE_TRIAL_ENABLED=True)


def _cloudflare_options():
    urls = [f"postgresql://{role}@db.neon.tech/reink_db?sslmode=verify-full"
            for role in ("machine", "dispatch", "expiry", "cleanup")]
    return dict(
        DATABASE_URL="postgresql://app@db.neon.tech/reink_db", CLOUDFLARE_ENABLED=True,
        EXTRACTION_QUOTA_ENABLED=True,
        CLOUDFLARE_MACHINE_DATABASE_URL=urls[0], CLOUDFLARE_DISPATCH_DATABASE_URL=urls[1],
        CLOUDFLARE_EXPIRY_DATABASE_URL=urls[2], CLOUDFLARE_CLEANUP_DATABASE_URL=urls[3],
        CLOUDFLARE_MACHINE_TOKEN="a" * 32, CLOUDFLARE_DISPATCH_TOKEN="b" * 32,
        CLOUDFLARE_EXPIRY_TOKEN="c" * 32, CLOUDFLARE_CLEANUP_TOKEN="d" * 32,
        CLOUDFLARE_CAPABILITY_KEY=base64.urlsafe_b64encode(b"e" * 32).decode(),
        PROVIDER_CREDENTIAL_ENCRYPTION_KEY=base64.urlsafe_b64encode(b"f" * 32).decode(),
        CLOUDFLARE_ACCOUNT_ID="a" * 32, CLOUDFLARE_QUEUE_ID="b" * 32,
        CLOUDFLARE_QUEUE_API_TOKEN="queue-token", R2_ENDPOINT_URL="https://storage.example.com",
        R2_BUCKET="documents", R2_ACCESS_KEY_ID="id", R2_SECRET_ACCESS_KEY="secret",
    )


@pytest.mark.parametrize("machine_target", ["other.neon.tech/reink_db", "db.neon.tech/other_db"])
def test_cloudflare_configuration_rejects_machine_database_mismatch(machine_target):
    from app.core.config import Settings

    options = _cloudflare_options()
    options["CLOUDFLARE_MACHINE_DATABASE_URL"] = f"postgresql://machine@{machine_target}?sslmode=verify-full"
    with pytest.raises(ValidationError, match="same database"):
        Settings(_env_file=None, **options)


def test_cloudflare_configuration_accepts_neon_pooled_and_direct_connections():
    from app.core.config import Settings

    options = _cloudflare_options()
    options["DATABASE_URL"] = "postgresql://app@ep-test-pooler.c-2.us-east-2.aws.neon.tech/reink_db"
    for role in ("MACHINE", "DISPATCH", "EXPIRY", "CLEANUP"):
        options[f"CLOUDFLARE_{role}_DATABASE_URL"] = (
            f"postgresql://{role.lower()}@ep-test.c-2.us-east-2.aws.neon.tech/reink_db?sslmode=verify-full"
        )
    assert Settings(_env_file=None, **options).CLOUDFLARE_ENABLED


def test_trial_upload_requires_notice_and_reserves_free_extraction(as_org, monkeypatch):
    from app.api.endpoints import provider_credentials
    import app.services.private_document_service as documents

    class Store:
        def __init__(self): self.objects = {}
        def put(self, key, data, content_type): self.objects[key] = data
        def get(self, key): return self.objects[key]
        def delete(self, key): self.objects.pop(key, None)

    store = Store()
    monkeypatch.setattr(documents, "storage_service", store)
    for name, value in {
        "CLOUDFLARE_TRIAL_ENABLED": True, "EXTRACTION_QUOTA_ENABLED": True,
        "EXTRACTION_GLOBAL_TRIAL_MONTHLY_LIMIT": 100,
        "EXTRACTION_GLOBAL_TRIAL_CALL_MONTHLY_LIMIT": 100,
        "LANDINGAI_TRIAL_API_KEY": "trial-key",
        "PROVIDER_CREDENTIAL_ENCRYPTION_KEY": base64.urlsafe_b64encode(b"a" * 32).decode(),
    }.items():
        monkeypatch.setattr(settings, name, value)
    org_id = "upload-" + uuid4().hex
    monkeypatch.setattr(settings, "TRIAL_ALLOWED_ORGANIZATION_IDS", [org_id])
    client = as_org(org_id)
    data = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.write(data)

    def upload():
        return client.post("/api/documents/upload", files={"file": ("sample.pdf", data.getvalue(), "application/pdf")})

    assert upload().status_code == 403
    assert not store.objects
    assert client.post("/api/provider-credentials/landingai/acknowledgment").status_code == 200
    response = upload()
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "queued"
    assert len(store.objects) == 1
    assert client.get("/api/documents/usage").json()["free_remaining"] == 4
    job_id = response.json()["job_id"]
    original = client.get(f"/api/documents/file/{job_id}")
    assert original.status_code == 200
    assert original.content == data.getvalue()
    assert original.headers["content-disposition"].startswith("inline")
    assert client.delete(f"/api/documents/{job_id}").status_code == 200
    assert client.get(f"/api/documents/file/{job_id}").status_code == 404


def test_trial_mode_cannot_bypass_disabled_trial_with_an_api_key(as_org, monkeypatch):
    monkeypatch.setattr(settings, "CLOUDFLARE_TRIAL_ENABLED", True)
    client = as_org("unavailable-" + uuid4().hex)
    response = client.post("/api/documents/upload", data={"api_key": "user-key"}, files={"file": ("sample.pdf", b"fake", "application/pdf")})
    assert response.status_code == 503


def test_machine_and_maintenance_routes_are_disabled_by_default(client):
    assert client.post("/api/cloudflare/jobs/job/attempts/attempt/claim").status_code == 503
    for name in ("cloudflare-dispatch", "expiry", "cleanup"):
        assert client.post(f"/api/maintenance/{name}").status_code == 503


def test_five_free_completions_then_customer_key(as_org, db_session, monkeypatch):
    import app.services.private_document_service as documents
    import app.api.endpoints.provider_credentials as credentials
    from app.api.endpoints.cloudflare import machine_db
    from app.core.tenancy import bind_session_to_org, get_tenant_db
    from app.main import app
    from app.models.extraction_job import ExtractionJob
    from sqlalchemy.orm import Session

    class Store:
        def __init__(self): self.objects = {}
        def put(self, key, data, content_type): self.objects[key] = data
        def get(self, key): return self.objects[key]
        def delete(self, key): self.objects.pop(key, None)

    monkeypatch.setattr(documents, "storage_service", Store())
    monkeypatch.setattr(credentials, "validate_landingai_key", lambda key: True)
    for name, value in {
        "CLOUDFLARE_TRIAL_ENABLED": True, "CLOUDFLARE_ENABLED": True,
        "EXTRACTION_QUOTA_ENABLED": True, "EXTRACTION_GLOBAL_TRIAL_MONTHLY_LIMIT": 100000,
        "EXTRACTION_GLOBAL_TRIAL_CALL_MONTHLY_LIMIT": 100000,
        "EXTRACTION_ATTEMPTS_PER_MINUTE": 100,
        "LANDINGAI_TRIAL_API_KEY": "test-trial-key",
        "PROVIDER_CREDENTIAL_ENCRYPTION_KEY": base64.urlsafe_b64encode(b"a" * 32).decode(),
    }.items():
        monkeypatch.setattr(settings, name, value)
    org_id = "trial-completion-" + uuid4().hex
    monkeypatch.setattr(settings, "TRIAL_ALLOWED_ORGANIZATION_IDS", [org_id])
    client = as_org(org_id)
    connection = db_session.connection()
    def scoped_request():
        with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
            bind_session_to_org(session, org_id)
            yield session
    app.dependency_overrides[get_tenant_db] = scoped_request
    app.dependency_overrides[machine_db] = scoped_request
    try:
        assert client.post("/api/provider-credentials/landingai/acknowledgment").status_code == 200
        stream = io.BytesIO()
        writer = PdfWriter()
        writer.add_blank_page(width=612, height=792)
        writer.write(stream)
        pdf = stream.getvalue()

        def upload():
            return client.post("/api/documents/upload", files={"file": ("ordinary.pdf", pdf, "application/pdf")})

        def complete(response, expected_key):
            assert response.status_code == 200, response.text
            job_id = response.json()["job_id"]
            db_session.expire_all()
            attempt_id = db_session.get(ExtractionJob, job_id).selected_attempt_id
            base = f"/api/cloudflare/jobs/{job_id}/attempts/{attempt_id}"
            claim = client.post(base + "/claim", headers={"X-Extraction-Protocol": "2"})
            assert claim.status_code == 200, claim.text
            token = claim.json()["checkpoint_token"]
            headers = {"X-Checkpoint-Token": token}
            assert client.get(base + "/credential", headers=headers).json() == {"api_key": expected_key}
            assert client.post(base + "/provider-start", headers=headers).status_code == 200
            event = {"schema_version": "1", "job_id": job_id, "attempt_id": attempt_id,
                     "event_id": "terminal", "status": "completed",
                     "result": {"contract_data": {"contract_name": "Synthetic treaty"}, "parties_data": []}}
            checkpoint = client.post(base + "/checkpoint", json=event, headers=headers)
            assert checkpoint.status_code == 200, checkpoint.text
            delivered = client.post(base + "/deliver")
            assert delivered.status_code == 200, delivered.text
            status = client.get(f"/api/documents/status/{job_id}")
            assert status.json()["result"]["contract_data"]["contract_name"] == "Synthetic treaty"
            return job_id

        for _ in range(5):
            complete(upload(), "test-trial-key")
        assert client.get("/api/documents/usage").json()["free_remaining"] == 0
        assert upload().status_code == 429
        saved = client.put("/api/provider-credentials/landingai", json={"api_key": "customer-key"})
        assert saved.status_code == 200, saved.text
        completed_id = complete(upload(), "customer-key")
        assert client.get("/api/documents/usage").json()["monthly_successes"] == 6
        from app.services.agent_service import agent_service
        monkeypatch.setattr(agent_service, "_offline_mode", True)
        guided = client.post("/api/agents/intake", json={"job_id": completed_id, "user_input": "Review this contract"})
        assert guided.status_code == 200, guided.text
        assert guided.json()["status"] == "ready"
        assert guided.json()["contract_data"]["contract_name"] == "Synthetic treaty"
        failed = upload()
        job_id = failed.json()["job_id"]
        db_session.expire_all()
        attempt_id = db_session.get(ExtractionJob, job_id).selected_attempt_id
        base = f"/api/cloudflare/jobs/{job_id}/attempts/{attempt_id}"
        token = client.post(base + "/claim", headers={"X-Extraction-Protocol": "2"}).json()["checkpoint_token"]
        event = {"schema_version": "1", "job_id": job_id, "attempt_id": attempt_id,
                 "event_id": "terminal", "status": "failed",
                 "error": {"code": "EXTRACTION_FAILED", "message": "Extraction failed.", "retryable": True}}
        assert client.post(base + "/checkpoint", json=event, headers={"X-Checkpoint-Token": token}).status_code == 200
        assert client.post(base + "/deliver").status_code == 200
        retry = client.post(f"/api/documents/{job_id}/retry")
        assert retry.status_code == 200, retry.text
        assert retry.json()["status"] == "queued"
        assert client.post(f"/api/documents/{job_id}/retry").status_code == 409
    finally:
        app.dependency_overrides.pop(machine_db, None)


def test_cloudflare_transport_requires_quotas_even_without_trial():
    from app.core.config import Settings

    options = _cloudflare_options()
    options.update(CLOUDFLARE_TRIAL_ENABLED=False, EXTRACTION_QUOTA_ENABLED=False)
    with pytest.raises(ValidationError, match="CLOUDFLARE_ENABLED requires EXTRACTION_QUOTA_ENABLED"):
        Settings(_env_file=None, **options)
