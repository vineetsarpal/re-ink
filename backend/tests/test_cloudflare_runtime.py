"""Machine database pools are sized for the Cloudflare consumer's concurrency."""
import pytest
from pydantic import ValidationError

from app.core import cloudflare_runtime
from app.core.config import settings

URL = "postgresql://user:pass@localhost:5432/pool_sizing_only"


@pytest.fixture(autouse=True)
def enabled(monkeypatch):
    monkeypatch.setattr(settings, "CLOUDFLARE_ENABLED", True)
    monkeypatch.setattr(settings, "EXTRACTION_QUOTA_ENABLED", True)
    monkeypatch.setattr(settings, "CLOUDFLARE_MACHINE_DATABASE_URL", URL)
    for name in ("CLOUDFLARE_MACHINE_POOL_SIZE", "CLOUDFLARE_MACHINE_POOL_MAX_OVERFLOW",
                 "CLOUDFLARE_MACHINE_POOL_TIMEOUT_SECONDS"):
        monkeypatch.delenv(name, raising=False)
    cloudflare_runtime._factory.cache_clear()
    cloudflare_runtime.pool_settings.cache_clear()
    yield
    cloudflare_runtime._factory.cache_clear()
    cloudflare_runtime.pool_settings.cache_clear()


def _pool():
    return cloudflare_runtime.machine_factory().kw["bind"].pool


def test_default_pool_allows_an_overlapping_retry_but_stays_small():
    pool = _pool()
    assert pool.size() == 2
    assert pool._max_overflow == 1
    assert pool._timeout == 5


def test_pool_size_is_configurable(monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_MACHINE_POOL_SIZE", "4")
    monkeypatch.setenv("CLOUDFLARE_MACHINE_POOL_MAX_OVERFLOW", "0")
    monkeypatch.setenv("CLOUDFLARE_MACHINE_POOL_TIMEOUT_SECONDS", "3")
    pool = _pool()
    assert (pool.size(), pool._max_overflow, pool._timeout) == (4, 0, 3)


@pytest.mark.parametrize("name,value", [("CLOUDFLARE_MACHINE_POOL_SIZE", "0"),
                                        ("CLOUDFLARE_MACHINE_POOL_SIZE", "50"),
                                        ("CLOUDFLARE_MACHINE_POOL_MAX_OVERFLOW", "-1"),
                                        ("CLOUDFLARE_MACHINE_POOL_TIMEOUT_SECONDS", "60")])
def test_unsafe_pool_settings_are_rejected(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(ValidationError):
        cloudflare_runtime.machine_factory()


def _bound_url(factory):
    return factory().kw["bind"].url


@pytest.mark.parametrize("name", ["machine", "dispatch", "expiry", "cleanup", "purge"])
def test_verify_full_without_root_cert_uses_bundled_ca(monkeypatch, name):
    import certifi
    monkeypatch.setattr(settings, f"CLOUDFLARE_{name.upper()}_DATABASE_URL",
                        "postgresql://role:secret@ep-x.aws.neon.tech/reink_db?sslmode=verify-full")
    url = _bound_url(getattr(cloudflare_runtime, f"{name}_factory"))
    assert url.query["sslmode"] == "verify-full"
    assert url.query["sslrootcert"] == certifi.where()


def test_explicit_root_cert_is_respected(monkeypatch):
    monkeypatch.setattr(settings, "CLOUDFLARE_MACHINE_DATABASE_URL",
                        "postgresql://role:secret@ep-x.aws.neon.tech/reink_db?sslmode=verify-full&sslrootcert=system")
    assert _bound_url(cloudflare_runtime.machine_factory).query["sslrootcert"] == "system"


def test_non_verify_full_url_is_unchanged():
    assert "sslrootcert" not in _bound_url(cloudflare_runtime.machine_factory).query
