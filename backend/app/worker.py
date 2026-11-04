"""Restartable dispatcher: python -m app.worker [--once] [--cleanup]."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import time
import math
import httpx
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from fastapi import HTTPException
from app.core.config import settings
from app.services.workflow_service import lease_dispatch, finish_dispatch, sweep_expired, lease_cleanup, finish_cleanup


def make_session_factory():
    from app.core.service_auth import validate_worker_database_url
    url = settings.WORKFLOW_WORKER_DATABASE_URL
    validate_worker_database_url(url)
    url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    engine = create_engine(url, pool_size=2, max_overflow=0, pool_pre_ping=True)
    return sessionmaker(bind=engine, autoflush=False)


@contextmanager
def scoped_session(factory):
    db = factory()
    @event.listens_for(db, "after_begin")
    def bind(session, transaction, connection):
        connection.exec_driver_sql("SELECT set_config('app.current_org', %s, true)", (settings.WORKFLOW_CUSTOMER_ORG_ID,))
        connection.exec_driver_sql("SET LOCAL lock_timeout = '5s'")
        connection.exec_driver_sql("SET LOCAL statement_timeout = '15s'")
    try:
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def retry_after_seconds(value):
    if not value:
        return None
    try:
        seconds = float(value)
        return min(60, max(0, seconds)) if math.isfinite(seconds) else None
    except ValueError:
        try:
            return min(60, max(0, (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds()))
        except (TypeError, ValueError, OverflowError):
            return None


def dispatch_once(factory, client=None):
    from app.schemas.workflow import validate_acceptance
    with scoped_session(factory) as db:
        sweep_expired(db)
        lease = lease_dispatch(db)
    if not lease:
        return False
    accepted = permanent = False
    retry_after = None
    own_client = client is None
    client = client or httpx.Client(timeout=settings.WORKFLOW_HTTP_TIMEOUT_SECONDS, follow_redirects=False)
    try:
        response = client.post(settings.WORKFLOW_WEBHOOK_URL, json=lease["payload"], headers={"Authorization": f"Bearer {settings.WORKFLOW_DISPATCH_TOKEN}"})
        retry_after = retry_after_seconds(response.headers.get("Retry-After"))
        if response.status_code == 202:
            try:
                validate_acceptance(response.json(), lease["payload"]["job_id"], lease["attempt_id"])
                accepted = True
            except (ValueError, TypeError):
                pass
        elif 400 <= response.status_code < 500 and response.status_code not in (408, 429):
            permanent = True
    except httpx.HTTPError:
        pass
    finally:
        if own_client:
            client.close()
    with scoped_session(factory) as db:
        try:
            finish_dispatch(db, lease, accepted=accepted, permanent=permanent, retry_after=retry_after)
        except HTTPException as exc:
            if exc.status_code not in (404, 409, 410):
                raise
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--cleanup", action="store_true")
    args = parser.parse_args()
    if not settings.WORKFLOW_CUSTOMER_ORG_ID:
        raise SystemExit("Workflow customer scope is required")
    if not args.cleanup and not (settings.WORKFLOW_WEBHOOK_URL and settings.WORKFLOW_DISPATCH_TOKEN):
        raise SystemExit("Workflow configuration is incomplete")
    if settings.WORKFLOW_HTTP_TIMEOUT_SECONDS >= settings.WORKFLOW_LEASE_SECONDS:
        raise SystemExit("HTTP timeout must be shorter than dispatch lease")
    factory = make_session_factory()
    while True:
        if args.cleanup:
            from app.services.storage_service import storage_service
            with scoped_session(factory) as db:
                cleanup = lease_cleanup(db)
            worked = cleanup is not None
            if cleanup:
                succeeded = False
                try:
                    storage_service.delete(cleanup["storage_key"])
                    succeeded = True
                except Exception:
                    pass
                with scoped_session(factory) as db:
                    finish_cleanup(db, cleanup, succeeded)
        else:
            worked = dispatch_once(factory)
        if args.once:
            break
        if not worked:
            time.sleep(1)


if __name__ == "__main__":
    main()
