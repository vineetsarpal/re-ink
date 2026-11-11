"""Factories for explicitly separate Cloudflare machine database identities."""
from functools import lru_cache

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings


def require_enabled():
    if not settings.CLOUDFLARE_ENABLED:
        raise HTTPException(503, "Cloudflare extraction is disabled")


@lru_cache(maxsize=4)
def _factory(url: str):
    url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    engine = create_engine(url, pool_size=1, max_overflow=0, pool_timeout=2,
                           pool_pre_ping=True, connect_args={"connect_timeout": 3})
    return sessionmaker(bind=engine, autoflush=False)


def machine_factory():
    require_enabled()
    return _factory(settings.CLOUDFLARE_MACHINE_DATABASE_URL)


def dispatch_factory():
    require_enabled()
    return _factory(settings.CLOUDFLARE_DISPATCH_DATABASE_URL)


def expiry_factory():
    require_enabled()
    return _factory(settings.CLOUDFLARE_EXPIRY_DATABASE_URL)


def cleanup_factory():
    require_enabled()
    return _factory(settings.CLOUDFLARE_CLEANUP_DATABASE_URL)
