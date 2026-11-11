"""Machine database pools are sized for the Cloudflare consumer's concurrency."""
import pytest
from pydantic import ValidationError

from app.core import cloudflare_runtime
from app.core.config import settings

URL = "postgresql://user:pass@localhost:5432/pool_sizing_only"


@pytest.fixture(autouse=True)
def enabled(monkeypatch):
    monkeypatch.setattr(settings, "CLOUDFLARE_ENABLED", True)
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
