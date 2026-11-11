"""Lifecycle integration tests use independent real PostgreSQL connections."""
from conftest import seed_trial_quota
from datetime import timedelta
import uuid
import pytest
from fastapi import HTTPException
from sqlalchemy import event, select, delete
from sqlalchemy.orm import sessionmaker
from app.models.extraction_job import ExtractionJob
from app.models.workflow import ExtractionAttempt, WorkflowOutbox, WorkflowReceipt, StorageCleanup
from app.services import workflow_service as svc
from app.schemas.workflow import EVENT_ADAPTER
from app.core.config import settings
from app.services.extraction_quota import quota_usage, start_provider_call


@pytest.fixture
def sessions(restricted_engine):
    org = "lifecycle-" + uuid.uuid4().hex
    factory = sessionmaker(bind=restricted_engine, autoflush=False, expire_on_commit=False)
    opened = []
    def make():
        db = factory()
        @event.listens_for(db, "after_begin")
        def bind(session, transaction, connection):
            connection.exec_driver_sql("SELECT set_config('app.current_org', %s, true)", (org,))
        opened.append(db)
        return db
    yield make, org
    for db in opened:
        db.close()
    db = make()
    for model in (WorkflowReceipt, WorkflowOutbox, ExtractionAttempt, StorageCleanup, ExtractionJob):
        db.execute(delete(model))
    db.commit()
    db.close()


def create(db, org):
    return svc.create_workflow_job(db, {"job_id": uuid.uuid4().hex, "filename": "synthetic.pdf", "storage_key": "original-" + uuid.uuid4().hex, "content_type": "application/pdf", "size_bytes": 10, "sha256": "a"*64}, org)


def event_for(job, status="completed", event_id="result", attempt_id=None):
    data = {"schema_version": "1", "job_id": job.job_id, "attempt_id": attempt_id or job.selected_attempt_id, "event_id": event_id, "status": status}
    if status == "completed":
        data["result"] = {"contract_data": {"contract_name": "Synthetic treaty"}, "parties_data": []}
    if status == "failed":
        data["error"] = {"code": "UNREADABLE_DOCUMENT", "message": "The document could not be read.", "retryable": False}
    return EVENT_ADAPTER.validate_python(data)


def test_completed_stop_loss_result_is_available_for_guided_review(sessions):
    make, org = sessions
    db = make()
    job = create(db, org)
    event = event_for(job)
    payload = event.model_dump(mode="json", exclude_unset=True)
    payload["result"]["contract_data"]["contract_sub_type"] = "stop_loss"
    svc.ingest_event(db, EVENT_ADAPTER.validate_python(payload))
    db.commit()
    db.expire_all()
    saved = db.get(ExtractionJob, job.job_id)
    from app.schemas.document import ExtractionResult
    result = ExtractionResult.model_validate(saved.parsed_results)
    assert saved.status == "completed"
    assert result.contract_data["contract_sub_type"] == "stop_loss"


def test_quota_reservation_tracks_success_and_failure(sessions, monkeypatch):
    import base64
    monkeypatch.setattr(settings, "EXTRACTION_QUOTA_ENABLED", True)
    monkeypatch.setattr(settings, "EXTRACTION_GLOBAL_TRIAL_MONTHLY_LIMIT", 100)
    monkeypatch.setattr(settings, "EXTRACTION_GLOBAL_TRIAL_CALL_MONTHLY_LIMIT", 100)
    monkeypatch.setattr(settings, "PROVIDER_CREDENTIAL_ENCRYPTION_KEY", base64.urlsafe_b64encode(b"x" * 32).decode())
    monkeypatch.setattr(settings, "LANDINGAI_TRIAL_API_KEY", "trial-test-key")
    make, org = sessions
    db = make()
    seed_trial_quota(db, org)
    first = create(db, org)
    second = create(db, org)
    assert quota_usage(db, org).pending == 2
    start_provider_call(db, org, first.selected_attempt_id, global_trial_call_limit=100)
    svc.ingest_event(db, event_for(first))
    svc.ingest_event(db, event_for(second, "failed"))
    usage = quota_usage(db, org)
    assert (usage.pending, usage.monthly_successes, usage.free_successes) == (0, 1, 1)
    db.rollback()


def test_quota_releases_on_timeout_and_delete_and_reserves_on_retry(sessions, monkeypatch):
    import base64
    monkeypatch.setattr(settings, "EXTRACTION_QUOTA_ENABLED", True)
    monkeypatch.setattr(settings, "EXTRACTION_GLOBAL_TRIAL_MONTHLY_LIMIT", 100)
    monkeypatch.setattr(settings, "EXTRACTION_GLOBAL_TRIAL_CALL_MONTHLY_LIMIT", 100)
    monkeypatch.setattr(settings, "PROVIDER_CREDENTIAL_ENCRYPTION_KEY", base64.urlsafe_b64encode(b"x" * 32).decode())
    monkeypatch.setattr(settings, "LANDINGAI_TRIAL_API_KEY", "trial-test-key")
    make, org = sessions
    db = make()
    seed_trial_quota(db, org)
    timed_out = create(db, org)
    deleted = create(db, org)
    attempt = db.get(ExtractionAttempt, timed_out.selected_attempt_id)
    attempt.deadline_at = svc.now(db) - timedelta(seconds=1)
    db.flush()
    svc.expire_job(db, timed_out.job_id)
    svc.delete_job(db, deleted.job_id)
    assert quota_usage(db, org).pending == 0
    svc.retry_job(db, timed_out.job_id)
    assert quota_usage(db, org).pending == 1
    db.rollback()


def test_queued_attempt_keeps_its_credential_after_replacement(sessions, monkeypatch):
    import base64
    from app.models.provider_credential import ProviderCredential
    from app.services.provider_credentials import encrypt_credential
    from app.services.workflow_service import get_attempt_credential

    key = base64.urlsafe_b64encode(b"x" * 32).decode()
    monkeypatch.setattr(settings, "EXTRACTION_QUOTA_ENABLED", True)
    monkeypatch.setattr(settings, "PROVIDER_CREDENTIAL_ENCRYPTION_KEY", key)
    make, org = sessions
    db = make()
    credential = ProviderCredential(org_id=org, provider="landingai", ciphertext=encrypt_credential("first-key", org, "landingai", key))
    db.add(credential)
    db.flush()
    job = create(db, org)
    credential.ciphertext = encrypt_credential("replacement-key", org, "landingai", key)
    db.flush()
    svc.claim_attempt(db, job.job_id, job.selected_attempt_id, "worker-owner")
    with pytest.raises(HTTPException):
        get_attempt_credential(db, job.job_id, job.selected_attempt_id, "other-worker")
    assert get_attempt_credential(db, job.job_id, job.selected_attempt_id, "worker-owner") == "first-key"
    start_provider_call(db, org, job.selected_attempt_id, global_trial_call_limit=100)
    svc.ingest_event(db, event_for(job))
    from app.models.extraction_quota import QuotaReservation
    assert db.get(QuotaReservation, (org, job.selected_attempt_id)).credential_snapshot is None
    assert get_attempt_credential(db, job.job_id, job.selected_attempt_id, "worker-owner") is None
    db.rollback()


def test_missing_trial_credential_fails_closed_and_rolls_back_reservation(sessions, monkeypatch):
    import base64
    monkeypatch.setattr(settings, "EXTRACTION_QUOTA_ENABLED", True)
    monkeypatch.setattr(settings, "EXTRACTION_GLOBAL_TRIAL_MONTHLY_LIMIT", 100)
    monkeypatch.setattr(settings, "EXTRACTION_GLOBAL_TRIAL_CALL_MONTHLY_LIMIT", 100)
    monkeypatch.setattr(settings, "PROVIDER_CREDENTIAL_ENCRYPTION_KEY", base64.urlsafe_b64encode(b"x" * 32).decode())
    monkeypatch.setattr(settings, "LANDINGAI_TRIAL_API_KEY", "")
    make, org = sessions
    db = make()
    seed_trial_quota(db, org)
    with pytest.raises(HTTPException) as exc:
        create(db, org)
    assert exc.value.status_code == 503
    db.rollback()
    assert quota_usage(db, org).pending == 0
    db.rollback()


def test_sweeper_expires_at_most_one_job_per_transaction(sessions):
    make, org = sessions
    db = make()
    first, second = create(db, org), create(db, org)
    db.get(ExtractionAttempt, first.selected_attempt_id).deadline_at = svc.now(db) - timedelta(seconds=1)
    db.get(ExtractionAttempt, second.selected_attempt_id).deadline_at = svc.now(db) - timedelta(seconds=1)
    db.commit()
    assert svc.sweep_expired(db) == 1
    db.commit()
    assert svc.sweep_expired(db) == 1
    db.commit()


def test_atomic_creation_rollback(sessions):
    make, org = sessions
    db = make()
    job = create(db, org)
    identity = job.job_id
    db.rollback()
    other = make()
    assert other.get(ExtractionJob, identity) is None
    assert other.scalar(select(WorkflowOutbox)) is None


def test_competing_leases_and_restart_fencing(sessions):
    make, org = sessions
    db = make()
    job = create(db, org)
    db.commit()
    old = svc.lease_dispatch(db)
    other = make()
    assert svc.lease_dispatch(other) is None
    other.commit()
    db.commit()
    row = db.get(WorkflowOutbox, old["attempt_id"])
    row.lease_until = svc.now(db) - timedelta(seconds=1)
    db.commit()
    new = svc.lease_dispatch(other)
    other.commit()
    assert old["attempt_id"] == new["attempt_id"]
    assert old["token"] != new["token"]
    assert svc.finish_dispatch(db, old, accepted=True) is False
    db.commit()
    assert svc.finish_dispatch(other, new, accepted=True)
    other.commit()
    assert other.get(ExtractionJob, job.job_id).status == "processing"


def test_transport_retry_preserves_attempt(sessions):
    make, org = sessions
    db = make()
    job = create(db, org)
    db.commit()
    lease = svc.lease_dispatch(db)
    db.commit()
    assert svc.finish_dispatch(db, lease, retry_after=0)
    db.commit()
    row = db.get(WorkflowOutbox, lease["attempt_id"])
    row.next_delivery_at = svc.now(db) - timedelta(seconds=1)
    db.commit()
    retry = svc.lease_dispatch(db)
    assert retry["attempt_id"] == job.selected_attempt_id
    assert retry["count"] == 2


def test_claim_owner_and_lost_ack(sessions):
    make, org = sessions
    db = make()
    job = create(db, org)
    db.commit()
    lease = svc.lease_dispatch(db)
    db.commit()
    owner = svc.claim_attempt(db, job.job_id, job.selected_attempt_id, "execution-a")
    db.commit()
    assert owner["decision"] == "run"
    assert svc.claim_attempt(db, job.job_id, job.selected_attempt_id, "execution-a") == owner
    assert svc.claim_attempt(db, job.job_id, job.selected_attempt_id, "execution-b")["decision"] == "already_claimed"
    assert not svc.finish_dispatch(db, lease, permanent=True)
    db.commit()
    assert svc.lease_dispatch(db) is None
    assert db.get(ExtractionJob, job.job_id).status == "processing"


def test_early_callback_replay_conflict_and_late_ack(sessions):
    make, org = sessions
    db = make()
    job = create(db, org)
    db.commit()
    lease = svc.lease_dispatch(db)
    db.commit()
    event = event_for(job)
    ack = svc.ingest_event(db, event)
    db.commit()
    assert svc.ingest_event(db, event) == ack
    with pytest.raises(HTTPException) as conflict:
        svc.ingest_event(db, event_for(job, "failed"))
    assert conflict.value.status_code == 409
    db.rollback()
    assert not svc.finish_dispatch(db, lease, accepted=True)
    db.commit()
    assert db.get(ExtractionJob, job.job_id).status == "completed"
    assert svc.ingest_event(db, event_for(job, "processing", "new-progress"))["rejection"] == 409


@pytest.mark.parametrize("started,code", [(False, "DISPATCH_TIMEOUT"), (True, "PROCESSING_TIMEOUT")])
def test_deadline_and_no_claim_reassignment(sessions, started, code):
    make, org = sessions
    db = make()
    job = create(db, org)
    if started:
        svc.claim_attempt(db, job.job_id, job.selected_attempt_id, "dead-owner")
    attempt = db.get(ExtractionAttempt, job.selected_attempt_id)
    attempt.deadline_at = svc.now(db) - timedelta(seconds=1)
    db.commit()
    assert svc.ingest_event(db, event_for(job))["rejection"] == 409
    db.commit()
    assert attempt.error_code == code
    assert svc.claim_attempt(db, job.job_id, attempt.attempt_id, "replacement")["rejection"] == 409
    assert svc.lease_dispatch(db) is None
    assert svc.expire_job(db, job.job_id).status == "timed_out"


def test_retry_current_attempt_fence(sessions):
    make, org = sessions
    db = make()
    job = create(db, org)
    old_id = job.selected_attempt_id
    svc.ingest_event(db, event_for(job, "failed"))
    db.commit()
    svc.retry_job(db, job.job_id)
    db.commit()
    assert old_id != job.selected_attempt_id
    assert job.status == "queued" and job.parsed_results is None
    assert db.get(ExtractionAttempt, old_id).status == "failed"
    other = make()
    with pytest.raises(HTTPException) as competing:
        svc.retry_job(other, job.job_id)
    assert competing.value.status_code == 409
    other.rollback()
    with pytest.raises(HTTPException):
        svc.ingest_event(db, event_for(job, attempt_id=old_id))


def test_completed_cannot_retry(sessions):
    make, org = sessions
    db = make()
    job = create(db, org)
    svc.ingest_event(db, event_for(job))
    db.commit()
    with pytest.raises(HTTPException) as exc:
        svc.retry_job(db, job.job_id)
    assert exc.value.status_code == 409


def test_delete_revokes_and_durable_cleanup(sessions):
    make, org = sessions
    db = make()
    job = create(db, org)
    callback = event_for(job)
    attempt_id = job.selected_attempt_id
    db.commit()
    svc.delete_job(db, job.job_id)
    db.commit()
    with pytest.raises(HTTPException) as exc:
        svc.ingest_event(db, callback)
    assert exc.value.status_code == 410
    with pytest.raises(HTTPException) as exc:
        svc.claim_attempt(db, job.job_id, attempt_id, "owner")
    assert exc.value.status_code == 410
    assert svc.lease_dispatch(db) is None
    assert db.get(ExtractionAttempt, attempt_id) is None
    lease = svc.lease_cleanup(db)
    db.commit()
    assert svc.finish_cleanup(db, lease, False)
    db.commit()
    row = db.get(StorageCleanup, lease["cleanup_id"])
    row.next_attempt_at = svc.now(db) - timedelta(seconds=1)
    db.commit()
    retry = svc.lease_cleanup(db)
    db.commit()
    assert retry["storage_key"] == lease["storage_key"]
    assert svc.finish_cleanup(db, lease, True) is False
    assert svc.finish_cleanup(db, retry, True)
    db.commit()
    with pytest.raises(HTTPException) as exc:
        svc.ingest_event(db, callback)
    assert exc.value.status_code == 404


def test_cross_tenant_fence(sessions):
    make, org = sessions
    db = make()
    job = create(db, org)
    db.commit()
    other = make()
    from app.core.tenancy import bind_session_to_org
    bind_session_to_org(other, "other-org")
    with pytest.raises(HTTPException) as exc:
        svc.claim_attempt(other, job.job_id, job.selected_attempt_id, "owner")
    assert exc.value.status_code == 404


def test_concurrent_claims_choose_one_owner(sessions):
    from concurrent.futures import ThreadPoolExecutor
    make, org = sessions
    db = make()
    job = create(db, org)
    db.commit()
    def claim(key):
        own = make()
        result = svc.claim_attempt(own, job.job_id, job.selected_attempt_id, key)
        own.commit()
        return result["decision"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        decisions = list(pool.map(claim, ["owner-a", "owner-b"]))
    assert sorted(decisions) == ["already_claimed", "run"]


def test_concurrent_retries_select_one_replacement(sessions):
    from concurrent.futures import ThreadPoolExecutor
    make, org = sessions
    db = make()
    job = create(db, org)
    svc.ingest_event(db, event_for(job, "failed"))
    db.commit()
    def retry(_):
        own = make()
        try:
            replacement = svc.retry_job(own, job.job_id)
            own.commit()
            return replacement.selected_attempt_id
        except HTTPException as exc:
            own.rollback()
            return exc.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(retry, [0, 1]))
    assert outcomes.count(409) == 1
    db.expire_all()
    assert len(list(db.scalars(select(ExtractionAttempt).where(ExtractionAttempt.job_id == job.job_id)))) == 2


def test_deadline_callback_race_is_terminal(sessions):
    from concurrent.futures import ThreadPoolExecutor
    make, org = sessions
    db = make()
    job = create(db, org)
    callback = event_for(job)
    db.get(ExtractionAttempt, job.selected_attempt_id).deadline_at = svc.now(db) - timedelta(seconds=1)
    db.commit()
    def expire():
        own = make()
        svc.expire_job(own, job.job_id)
        own.commit()
    def complete():
        own = make()
        ack = svc.ingest_event(own, callback)
        own.commit()
        return ack
    with ThreadPoolExecutor(max_workers=2) as pool:
        expiration = pool.submit(expire)
        completion = pool.submit(complete)
        expiration.result()
        assert completion.result()["rejection"] == 409
    db.expire_all()
    assert db.get(ExtractionJob, job.job_id).status == "timed_out"
    assert db.get(ExtractionJob, job.job_id).parsed_results is None


def test_event_identity_preserves_optional_presence(sessions):
    make, org = sessions
    db = make()
    job = create(db, org)
    callback = event_for(job)
    svc.ingest_event(db, callback)
    db.commit()
    changed = callback.model_dump(mode="json", exclude_unset=True)
    changed["workflow_execution_id"] = None
    with pytest.raises(HTTPException) as exc:
        svc.ingest_event(db, EVENT_ADAPTER.validate_python(changed))
    assert exc.value.status_code == 409
