from conftest import seed_trial_quota
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi import HTTPException
from app.core.tenancy import bind_session_to_org
from app.services.extraction_quota import reserve_extraction, settle_extraction, quota_usage, start_provider_call


NOW = datetime(2026, 11, 5, tzinfo=timezone.utc)


def test_extraction_attempt_rate_limit_is_per_org_and_resets_each_minute(db_session):
    bind_session_to_org(db_session, "rate-a")
    for attempt in ("one", "two"):
        reserve_extraction(db_session, "rate-a", attempt, has_customer_key=True,
                           global_trial_limit=0, per_minute_limit=2, at=NOW)
    with pytest.raises(HTTPException) as blocked:
        reserve_extraction(db_session, "rate-a", "three", has_customer_key=True,
                           global_trial_limit=0, per_minute_limit=2, at=NOW)
    assert blocked.value.status_code == 429
    bind_session_to_org(db_session, "rate-b")
    reserve_extraction(db_session, "rate-b", "one", has_customer_key=True,
                       global_trial_limit=0, per_minute_limit=2, at=NOW)
    bind_session_to_org(db_session, "rate-a")
    reserve_extraction(db_session, "rate-a", "three", has_customer_key=True,
                       global_trial_limit=0, per_minute_limit=2, at=NOW + timedelta(minutes=1))


def test_concurrent_extraction_attempts_cannot_exceed_rate_limit(restricted_engine):
    from sqlalchemy import delete
    from sqlalchemy.orm import Session
    from app.models.extraction_quota import ExtractionRate, OrganizationQuota, QuotaReservation

    org_id = "rate-concurrent-" + uuid4().hex
    barrier = Barrier(2)

    def admit(attempt):
        with Session(restricted_engine) as db:
            bind_session_to_org(db, org_id)
            barrier.wait(timeout=5)
            try:
                reserve_extraction(db, org_id, attempt, has_customer_key=True,
                                   global_trial_limit=0, per_minute_limit=1, at=NOW)
                db.commit()
                return "admitted"
            except HTTPException as exc:
                db.rollback()
                assert exc.status_code == 429
                return "blocked"

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(admit, ("one", "two"))) == ["admitted", "blocked"]
    finally:
        with Session(restricted_engine) as db:
            bind_session_to_org(db, org_id)
            db.execute(delete(QuotaReservation).where(QuotaReservation.org_id == org_id))
            db.execute(delete(ExtractionRate).where(ExtractionRate.org_id == org_id))
            db.execute(delete(OrganizationQuota).where(OrganizationQuota.org_id == org_id))
            db.commit()


def test_trial_extraction_counts_only_after_success(db_session):
    bind_session_to_org(db_session, "quota-org-a")
    seed_trial_quota(db_session, "quota-org-a")
    reservation = reserve_extraction(db_session, "quota-org-a", "attempt-a", has_customer_key=False, global_trial_limit=100, at=NOW)
    assert reservation.funding == "trial"
    assert quota_usage(db_session, "quota-org-a", at=NOW).monthly_successes == 0
    start_provider_call(db_session, "quota-org-a", "attempt-a", global_trial_call_limit=100, at=NOW)
    settle_extraction(db_session, "quota-org-a", "attempt-a", success=True, at=NOW)
    usage = quota_usage(db_session, "quota-org-a", at=NOW)
    assert (usage.monthly_successes, usage.free_successes) == (1, 1)


def test_five_free_reservations_block_more_until_a_failure_releases_one(db_session):
    bind_session_to_org(db_session, "quota-org-b")
    seed_trial_quota(db_session, "quota-org-b")
    for i in range(5):
        reserve_extraction(db_session, "quota-org-b", f"attempt-{i}", has_customer_key=False, global_trial_limit=100, at=NOW)
    with pytest.raises(HTTPException) as exc:
        reserve_extraction(db_session, "quota-org-b", "attempt-extra", has_customer_key=False, global_trial_limit=100, at=NOW)
    assert exc.value.status_code == 429
    settle_extraction(db_session, "quota-org-b", "attempt-0", success=False, at=NOW)
    reserve_extraction(db_session, "quota-org-b", "attempt-extra", has_customer_key=False, global_trial_limit=100, at=NOW)
    assert quota_usage(db_session, "quota-org-b", at=NOW).free_successes == 0


def test_concurrent_admissions_cannot_exceed_monthly_capacity(restricted_engine):
    from sqlalchemy import delete
    from sqlalchemy.orm import Session
    from app.models.extraction_quota import OrganizationQuota, QuotaReservation

    org_id = "quota-concurrent-" + uuid4().hex
    barrier = Barrier(2)

    def admit(attempt):
        with Session(restricted_engine) as db:
            bind_session_to_org(db, org_id)
            barrier.wait(timeout=5)
            try:
                reserve_extraction(db, org_id, attempt, has_customer_key=True, global_trial_limit=0, monthly_limit=1, at=NOW)
                db.commit()
                return "admitted"
            except HTTPException as exc:
                db.rollback()
                assert exc.status_code == 429
                return "blocked"

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(admit, ("attempt-1", "attempt-2"))) == ["admitted", "blocked"]
    finally:
        with Session(restricted_engine) as db:
            bind_session_to_org(db, org_id)
            db.execute(delete(QuotaReservation).where(QuotaReservation.org_id == org_id))
            db.execute(delete(OrganizationQuota).where(OrganizationQuota.org_id == org_id))
            db.commit()


def test_month_reset_preserves_free_balance_and_pending_capacity(db_session):
    bind_session_to_org(db_session, "quota-month")
    seed_trial_quota(db_session, "quota-month")
    reserve_extraction(db_session, "quota-month", "trial", has_customer_key=False, global_trial_limit=100, at=NOW)
    start_provider_call(db_session, "quota-month", "trial", global_trial_call_limit=100, at=NOW)
    settle_extraction(db_session, "quota-month", "trial", success=True, at=NOW)
    reserve_extraction(db_session, "quota-month", "pending", has_customer_key=True, global_trial_limit=0, at=NOW)
    december = datetime(2026, 12, 1, tzinfo=timezone.utc)
    usage = quota_usage(db_session, "quota-month", at=december)
    assert (usage.monthly_successes, usage.pending, usage.free_successes) == (0, 1, 1)
    start_provider_call(db_session, "quota-month", "pending", global_trial_call_limit=100, at=december)
    settle_extraction(db_session, "quota-month", "pending", success=True, at=december)
    assert quota_usage(db_session, "quota-month", at=december).monthly_successes == 1


def test_global_trial_cap_is_shared_and_does_not_block_customer_keys(db_session):
    from sqlalchemy import update
    from app.models.extraction_quota import GlobalQuota
    db_session.execute(update(GlobalQuota).values(month=NOW.date().replace(day=1), trial_successes=0, trial_pending=0, trial_starts=0))
    bind_session_to_org(db_session, "quota-global-a")
    seed_trial_quota(db_session, "quota-global-a")
    reserve_extraction(db_session, "quota-global-a", "attempt-a", has_customer_key=False, global_trial_limit=1, at=NOW)
    db_session.flush()
    bind_session_to_org(db_session, "quota-global-b")
    seed_trial_quota(db_session, "quota-global-b")
    with pytest.raises(HTTPException) as exc:
        reserve_extraction(db_session, "quota-global-b", "attempt-b", has_customer_key=False, global_trial_limit=1, at=NOW)
    assert exc.value.status_code == 429
    assert reserve_extraction(db_session, "quota-global-b", "attempt-b", has_customer_key=True, global_trial_limit=1, at=NOW).funding == "customer"


def test_terminal_attempt_cannot_be_admitted_again(db_session):
    bind_session_to_org(db_session, "quota-terminal")
    reserve_extraction(db_session, "quota-terminal", "attempt", has_customer_key=True, global_trial_limit=0, at=NOW)
    start_provider_call(db_session, "quota-terminal", "attempt", global_trial_call_limit=100, at=NOW)
    settle_extraction(db_session, "quota-terminal", "attempt", success=True, at=NOW)
    with pytest.raises(HTTPException) as exc:
        reserve_extraction(db_session, "quota-terminal", "attempt", has_customer_key=True, global_trial_limit=0, at=NOW)
    assert exc.value.status_code == 409


def test_failed_trial_provider_calls_still_count_toward_global_call_cap(db_session):
    from sqlalchemy import update
    from app.models.extraction_quota import GlobalQuota
    from app.services.extraction_quota import start_provider_call
    db_session.execute(update(GlobalQuota).values(month=NOW.date().replace(day=1), trial_successes=0, trial_pending=0, trial_starts=0))
    bind_session_to_org(db_session, "quota-start-a")
    seed_trial_quota(db_session, "quota-start-a")
    reserve_extraction(db_session, "quota-start-a", "attempt-a", has_customer_key=False, global_trial_limit=20, at=NOW)
    start_provider_call(db_session, "quota-start-a", "attempt-a", global_trial_call_limit=1, at=NOW)
    # Redelivery of the same attempt must not count as another call.
    start_provider_call(db_session, "quota-start-a", "attempt-a", global_trial_call_limit=1, at=NOW)
    settle_extraction(db_session, "quota-start-a", "attempt-a", success=False, at=NOW)
    reserve_extraction(db_session, "quota-start-a", "attempt-b", has_customer_key=False, global_trial_limit=20, at=NOW)
    with pytest.raises(HTTPException) as exc:
        start_provider_call(db_session, "quota-start-a", "attempt-b", global_trial_call_limit=1, at=NOW)
    assert exc.value.status_code == 429




@pytest.mark.parametrize("success", [True, False])
def test_unstarted_reservation_only_accepts_failure(db_session, success):
    bind_session_to_org(db_session, "unstarted-org")
    seed_trial_quota(db_session, "unstarted-org")
    reservation = reserve_extraction(db_session, "unstarted-org", "unstarted", has_customer_key=False, global_trial_limit=100)
    if success:
        with pytest.raises(HTTPException) as exc:
            settle_extraction(db_session, "unstarted-org", "unstarted", success=True)
        assert exc.value.status_code == 409
        assert reservation.status == "pending"
    else:
        assert settle_extraction(db_session, "unstarted-org", "unstarted", success=False).status == "failed"
