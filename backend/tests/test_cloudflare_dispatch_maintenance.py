"""Authenticated scheduling boundary for tenant-scoped queue delivery."""
from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_maintenance_requires_a_scheduler_credential():
    from app.api.endpoints.cloudflare_dispatch_maintenance import router, maintenance_settings, MaintenanceSettings
    from app.services.cloudflare_dispatch import CloudflareQueueConfig

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[maintenance_settings] = lambda: MaintenanceSettings(
        token="x" * 32, queue=CloudflareQueueConfig("a" * 32, "b" * 32, "token", b"k" * 32, 600, 600))
    response = TestClient(app).post('/maintenance/cloudflare-dispatch')
    assert response.status_code == 401


def test_authenticated_maintenance_dispatches_a_bounded_batch(monkeypatch):
    import app.api.endpoints.cloudflare_dispatch_maintenance as endpoint
    from app.services.cloudflare_dispatch import CloudflareQueueConfig

    class FakeSession:
        def __enter__(self): return self
        def __exit__(self, *_args): return None
        def execute(self, _query): return None
        def scalar(self, _query): return 'trusted-org'

    app = FastAPI()
    app.include_router(endpoint.router)
    app.dependency_overrides[endpoint.maintenance_settings] = lambda: endpoint.MaintenanceSettings(
        token='x' * 32, queue=CloudflareQueueConfig('a' * 32, 'b' * 32, 'token', b'k' * 32, 600, 600))
    app.dependency_overrides[endpoint.maintenance_factory] = lambda: FakeSession
    calls = []
    monkeypatch.setattr(endpoint, 'dispatch_cloudflare_once', lambda _factory, org, _config, _client: calls.append(org) or True)
    response = TestClient(app).post('/maintenance/cloudflare-dispatch', headers={'Authorization': 'Bearer ' + 'x' * 32})
    assert response.status_code == 200
    assert response.json() == {'attempted': 5}
    assert calls == ['trusted-org'] * 5


def test_maintenance_starts_no_more_dispatches_after_time_budget(monkeypatch):
    import app.api.endpoints.cloudflare_dispatch_maintenance as endpoint
    from app.services.cloudflare_dispatch import CloudflareQueueConfig

    class FakeSession:
        def __enter__(self): return self
        def __exit__(self, *_args): return None
        def execute(self, _query): return None
        def scalar(self, _query): return 'trusted-org'

    app = FastAPI()
    app.include_router(endpoint.router)
    app.dependency_overrides[endpoint.maintenance_settings] = lambda: endpoint.MaintenanceSettings(
        token='x' * 32, queue=CloudflareQueueConfig('a' * 32, 'b' * 32, 'token', b'k' * 32, 600, 600))
    app.dependency_overrides[endpoint.maintenance_factory] = lambda: FakeSession
    clock = iter([0, 0, 16])
    monkeypatch.setattr(endpoint, 'monotonic', lambda: next(clock))
    calls = []
    monkeypatch.setattr(endpoint, 'dispatch_cloudflare_once', lambda _factory, org, _config, _client: calls.append(org) or True)
    response = TestClient(app).post('/maintenance/cloudflare-dispatch', headers={'Authorization': 'Bearer ' + 'x' * 32})
    assert response.status_code == 200
    assert response.json() == {'attempted': 1}
    assert calls == ['trusted-org']
