"""Organization trial limits through the quota service boundary."""
from conftest import seed_trial_quota
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from app.core.tenancy import bind_session_to_org
from app.services.extraction_quota import quota_usage, reserve_extraction, settle_extraction, start_provider_call


def test_five_free_attempts_are_reserved_and_only_successes_count(db_session):
    org = "trial-quota-organization"
    now = datetime(2026, 11, 10, tzinfo=timezone.utc)
    bind_session_to_org(db_session, org)
    seed_trial_quota(db_session, org)
    for number in range(5):
        reserve_extraction(db_session, org, f"attempt-{number}", has_customer_key=False, global_trial_limit=100000, at=now)
    with pytest.raises(HTTPException) as error:
        reserve_extraction(db_session, org, "sixth", has_customer_key=False, global_trial_limit=100000, at=now)
    assert error.value.status_code == 429
    start_provider_call(db_session, org, "attempt-0", global_trial_call_limit=100, at=now)
    settle_extraction(db_session, org, "attempt-0", success=True, at=now)
    settle_extraction(db_session, org, "attempt-1", success=False, at=now)
    usage = quota_usage(db_session, org, at=now)
    assert usage.monthly_successes == 1
    assert usage.free_successes == 1
    assert usage.free_pending == 3


def test_start_cap_blocks_new_free_reservations_but_not_customer_keys(db_session):
    org = "global-start-cap-organization"
    now = datetime(2026, 11, 10, tzinfo=timezone.utc)
    bind_session_to_org(db_session, org)
    seed_trial_quota(db_session, org)
    for number in range(100):
        attempt = f"cap-{number}"
        reserve_extraction(db_session, org, attempt, has_customer_key=False,
                           global_trial_limit=100, global_trial_call_limit=100,
                           per_minute_limit=200, at=now)
        start_provider_call(db_session, org, attempt, global_trial_call_limit=100, at=now)
        settle_extraction(db_session, org, attempt, success=False, at=now)
    with pytest.raises(HTTPException) as error:
        reserve_extraction(db_session, org, "cap-overflow", has_customer_key=False,
                           global_trial_limit=100, global_trial_call_limit=100,
                           per_minute_limit=200, at=now)
    assert error.value.status_code == 429
    customer = reserve_extraction(db_session, org, "customer-key", has_customer_key=True,
                                  global_trial_limit=100, global_trial_call_limit=100,
                                  per_minute_limit=200, at=now)
    assert customer.funding == "customer"
