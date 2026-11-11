from uuid import uuid4

import pytest
from fastapi import HTTPException

from test_trial_hardening import trial
from conftest import seed_trial_quota
from app.models.extraction_quota import OrganizationQuota
from app.services.extraction_quota import precheck_extraction, reserve_extraction


@pytest.mark.parametrize('seam', ['reserve', 'precheck', 'readonly'])
@pytest.mark.parametrize('counter', ['monthly_successes', 'monthly_attempts'])
def test_customer_uses_higher_monthly_caps(db_session, seam, counter):
    org = uuid4().hex
    seed_trial_quota(db_session, org)
    row = db_session.get(OrganizationQuota, org)
    setattr(row, counter, 1 if counter == 'monthly_successes' else 4)
    db_session.flush()

    def admit(customer):
        options = dict(has_customer_key=customer, global_trial_limit=100000,
            monthly_limit=1, attempt_limit=4, customer_monthly_limit=2, customer_attempt_limit=8)
        if seam == 'reserve':
            return reserve_extraction(db_session, org, uuid4().hex, **options)
        return precheck_extraction(db_session, org, read_only=seam == 'readonly', **options)

    with pytest.raises(HTTPException) as error:
        admit(False)
    assert error.value.status_code == 429
    admit(True)
    setattr(row, counter, 2 if counter == 'monthly_successes' else 8)
    db_session.flush()
    with pytest.raises(HTTPException) as error:
        admit(True)
    assert error.value.status_code == 429


@pytest.mark.parametrize('seam', ['reserve', 'precheck', 'readonly'])
def test_uncapped_only_bypasses_customer_monthly_caps(db_session, seam):
    org = uuid4().hex
    seed_trial_quota(db_session, org)
    def admit(customer):
        options = dict(has_customer_key=customer, global_trial_limit=100000,
            monthly_limit=0, attempt_limit=0, customer_monthly_limit=0,
            customer_attempt_limit=0, uncapped_customer=True)
        if seam == 'reserve':
            return reserve_extraction(db_session, org, uuid4().hex, **options)
        return precheck_extraction(db_session, org, read_only=seam == 'readonly', **options)
    admit(True)
    with pytest.raises(HTTPException) as error:
        admit(False)
    assert error.value.status_code == 429


def test_uncapped_customer_still_hits_rate_limit(db_session):
    org = uuid4().hex
    seed_trial_quota(db_session, org)
    options = dict(has_customer_key=True, global_trial_limit=0, global_trial_call_limit=0,
        customer_monthly_limit=0, customer_attempt_limit=0, uncapped_customer=True, per_minute_limit=1)
    reserve_extraction(db_session, org, 'first', **options)
    with pytest.raises(HTTPException) as error:
        reserve_extraction(db_session, org, 'second', **options)
    assert error.value.status_code == 429
    assert 'Too many' in error.value.detail


@pytest.mark.parametrize('uncapped', [False, True])
def test_upload_uses_customer_caps_and_reports_effective_limit(trial, monkeypatch, uncapped):
    from app.api.endpoints import provider_credentials
    from app.core.config import settings
    org, client, store, upload = trial
    monkeypatch.setattr(provider_credentials, 'validate_landingai_key', lambda key: True)
    monkeypatch.setattr(settings, 'EXTRACTION_GLOBAL_TRIAL_CALL_MONTHLY_LIMIT', 0)
    monkeypatch.setattr(settings, 'EXTRACTION_CUSTOMER_MONTHLY_LIMIT', 1)
    monkeypatch.setattr(settings, 'EXTRACTION_CUSTOMER_MONTHLY_ATTEMPT_LIMIT', 4)
    monkeypatch.setattr(settings, 'EXTRACTION_UNCAPPED_ORGANIZATION_IDS', [org] if uncapped else [])
    blocked = upload()
    assert blocked.status_code == 429
    assert 'temporarily unavailable' in blocked.json()['detail']
    assert not store.objects
    assert client.get('/api/documents/usage').json()['monthly_limit'] == settings.EXTRACTION_MONTHLY_LIMIT
    assert client.put('/api/provider-credentials/landingai', json={'api_key': 'customer-key'}).status_code == 200
    monkeypatch.setattr(settings, 'EXTRACTION_MONTHLY_LIMIT', 0)
    monkeypatch.setattr(settings, 'EXTRACTION_MONTHLY_ATTEMPT_LIMIT', 0)
    assert client.get('/api/documents/usage').json()['monthly_limit'] == (None if uncapped else 1)
    response = upload()
    assert response.status_code == 200, response.text
    response = upload()
    assert response.status_code == (200 if uncapped else 429), response.text


def test_trial_kill_switch_is_valid_runtime_configuration():
    from app.core.config import Settings
    from test_trial_upload_api import _cloudflare_options
    options = _cloudflare_options()
    options.update(CLOUDFLARE_TRIAL_ENABLED=True, LANDINGAI_TRIAL_API_KEY='trial-key',
        EXTRACTION_GLOBAL_TRIAL_MONTHLY_LIMIT=100, EXTRACTION_GLOBAL_TRIAL_CALL_MONTHLY_LIMIT=0)
    assert Settings(_env_file=None, **options).CLOUDFLARE_TRIAL_ENABLED is True


@pytest.mark.parametrize('seam', ['reserve', 'precheck', 'readonly'])
@pytest.mark.parametrize('uncapped', [False, True])
def test_zero_trial_call_cap_stops_only_trial_funding(db_session, seam, uncapped):
    org = uuid4().hex
    seed_trial_quota(db_session, org)
    def admit(customer):
        options = dict(has_customer_key=customer, global_trial_limit=100000,
            global_trial_call_limit=0, uncapped_customer=uncapped)
        if seam == 'reserve':
            return reserve_extraction(db_session, org, uuid4().hex, **options)
        return precheck_extraction(db_session, org, read_only=seam == 'readonly', **options)
    with pytest.raises(HTTPException) as error:
        admit(False)
    assert 'temporarily unavailable' in error.value.detail
    admit(True)
