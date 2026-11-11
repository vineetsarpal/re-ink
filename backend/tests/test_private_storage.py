"""Private object storage stays scoped and fails closed without credentials."""
import httpx
import pytest

from app.services.storage_service import StorageError, StorageService, tenant_prefix


def test_storage_requires_configuration(monkeypatch):
    monkeypatch.setattr("app.services.storage_service.settings.R2_ACCESS_KEY_ID", "")
    with pytest.raises(StorageError, match="unavailable"):
        StorageService().get(tenant_prefix("org-a") + "00000000-0000-0000-0000-000000000000/original.pdf")


def test_private_object_roundtrip_and_tenant_namespace(monkeypatch):
    from app.services import storage_service as module

    for name, value in {"STORAGE_BACKEND": "r2", "R2_ENDPOINT_URL": "https://storage.example",
                        "R2_BUCKET": "private", "R2_ACCESS_KEY_ID": "id", "R2_SECRET_ACCESS_KEY": "secret"}.items():
        monkeypatch.setattr(module.settings, name, value)
    objects = {}
    requests = []

    def handle(request):
        requests.append(request)
        assert request.headers["authorization"].startswith("AWS4-HMAC-SHA256 ")
        if request.method == "PUT":
            assert request.headers["if-none-match"] == "*"
            objects[request.url.path] = request.content
            return httpx.Response(200)
        if request.method == "GET":
            return httpx.Response(200, content=objects[request.url.path])
        del objects[request.url.path]
        return httpx.Response(204)

    real_client = httpx.Client
    monkeypatch.setattr(module.httpx, "Client", lambda **kwargs: real_client(transport=httpx.MockTransport(handle), **kwargs))
    key = tenant_prefix("org-a") + "00000000-0000-0000-0000-000000000000/original.pdf"
    assert not key.startswith(tenant_prefix("org-b"))
    store = StorageService()
    store.put(key, b"synthetic pdf", "application/pdf")
    assert store.get(key) == b"synthetic pdf"
    store.delete(key)
    assert not objects
    assert [request.method for request in requests] == ["PUT", "GET", "DELETE"]
