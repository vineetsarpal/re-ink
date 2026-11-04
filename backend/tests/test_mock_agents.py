"""Disabled agent routes keep permissions, with no provider implementation loaded."""
import sys
import pytest

@pytest.mark.parametrize('path,payload', [
    ('/api/agents/intake', {'job_id': 'unknown', 'user_input': 'Review', 'chat_history': []}),
    ('/api/agents/review', {'contract_id': 1, 'chat_history': []}),
])
def test_agents_disabled(client, path, payload):
    response = client.post(path, json=payload)
    assert response.status_code == 503
    assert 'disabled' in response.json()['detail'].lower()
    assert 'app.services.landingai_service' not in sys.modules
    assert 'app.services.agent_service' not in sys.modules

def test_offline_mock_route_removed(client):
    assert client.post('/api/documents/mock-job', json={}).status_code in {404, 405}

def test_public_capabilities_do_not_expose_integration_settings(client, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, 'WORKFLOW_UPLOADS_ENABLED', False)
    response = client.get('/api/system/config')
    assert response.status_code == 200
    assert response.json() == {
        'workflow_extraction_enabled': False, 'workflow_retry_available': False,
        'guided_intake_enabled': False, 'automated_review_enabled': False,
    }

def test_capabilities_require_configuration_and_upload_enable(client, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, 'WORKFLOW_UPLOADS_ENABLED', True)
    monkeypatch.setattr(settings, 'WORKFLOW_CUSTOMER_ORG_ID', 'org-example')
    monkeypatch.setattr(settings, 'WORKFLOW_WEBHOOK_URL', 'https://workflow.example/webhook')
    monkeypatch.setattr(settings, 'WORKFLOW_DISPATCH_TOKEN', 'dispatch-secret')
    monkeypatch.setattr(settings, 'WORKFLOW_SERVICE_TOKEN', 'service-secret')
    result = client.get('/api/system/config').json()
    assert result['workflow_extraction_enabled'] is True
    assert result['workflow_retry_available'] is True
    assert result['guided_intake_enabled'] is False
    assert result['automated_review_enabled'] is False
    monkeypatch.setattr(settings, 'WORKFLOW_SERVICE_TOKEN', '')
    assert client.get('/api/system/config').json()['workflow_extraction_enabled'] is False
