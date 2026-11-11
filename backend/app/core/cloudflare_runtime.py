"""Factories for explicitly separate Cloudflare machine database identities."""
from functools import lru_cache

import certifi

from fastapi import HTTPException
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.core.config import settings


class MachinePoolSettings(BaseSettings):
    """Machine-route pool per backend process.

    The example consumer runs max_batch_size=1, max_concurrency=1, so each Worker
    makes one sequential request; the second connection covers a retry that
    overlaps a request the Worker abandoned on timeout. Raise with concurrency.
    """
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")
    CLOUDFLARE_MACHINE_POOL_SIZE: int = Field(default=2, ge=1, le=20)
    CLOUDFLARE_MACHINE_POOL_MAX_OVERFLOW: int = Field(default=1, ge=0, le=20)
    CLOUDFLARE_MACHINE_POOL_TIMEOUT_SECONDS: int = Field(default=5, ge=1, le=30)


@lru_cache(maxsize=1)
def pool_settings() -> MachinePoolSettings:
    return MachinePoolSettings()


def require_enabled():
    if not settings.CLOUDFLARE_ENABLED:
        raise HTTPException(503, "Cloudflare extraction is disabled")


@lru_cache(maxsize=5)
def _factory(url: str, pool_size: int = 1, max_overflow: int = 0, pool_timeout: int = 2):
    url = make_url(url.replace("postgresql://", "postgresql+psycopg://", 1))
    if url.query.get("sslmode") == "verify-full" and "sslrootcert" not in url.query:
        # Bundled libpq can't locate the host CA store; pin a known bundle.
        url = url.update_query_dict({"sslrootcert": certifi.where()})
    engine = create_engine(url, pool_size=pool_size, max_overflow=max_overflow, pool_timeout=pool_timeout,
                           pool_pre_ping=True, connect_args={"connect_timeout": 3})
    return sessionmaker(bind=engine, autoflush=False)


def machine_factory():
    require_enabled()
    pool = pool_settings()
    return _factory(settings.CLOUDFLARE_MACHINE_DATABASE_URL, pool.CLOUDFLARE_MACHINE_POOL_SIZE,
                    pool.CLOUDFLARE_MACHINE_POOL_MAX_OVERFLOW, pool.CLOUDFLARE_MACHINE_POOL_TIMEOUT_SECONDS)


def dispatch_factory():
    require_enabled()
    return _factory(settings.CLOUDFLARE_DISPATCH_DATABASE_URL)


def expiry_factory():
    require_enabled()
    return _factory(settings.CLOUDFLARE_EXPIRY_DATABASE_URL)


def cleanup_factory():
    require_enabled()
    return _factory(settings.CLOUDFLARE_CLEANUP_DATABASE_URL)


def purge_factory():
    require_enabled()
    return _factory(settings.CLOUDFLARE_PURGE_DATABASE_URL)
