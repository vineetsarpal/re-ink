"""Tenant-scoped storage cleanup using a dedicated, restricted DB identity."""
from contextlib import contextmanager

from sqlalchemy import event, text

from app.services.workflow_service import finish_cleanup, lease_cleanup
from app.services.storage_service import tenant_prefix


@contextmanager
def _scoped_session(factory, org):
    db = factory()

    @event.listens_for(db, "after_begin")
    def bind(session, transaction, connection):
        connection.exec_driver_sql("SELECT set_config('app.current_org', %s, true)", (org,))
        connection.exec_driver_sql("SET LOCAL lock_timeout = '5s'")
        connection.exec_driver_sql("SET LOCAL statement_timeout = '15s'")

    try:
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        event.remove(db, "after_begin", bind)
        db.close()


def cleanup_next(factory, storage) -> bool:
    """Delete at most one due original while holding its database safety fence."""
    with factory() as db:
        org = db.scalar(text("SELECT public.reink_next_cleanup_org()"))
    if org is None:
        return False
    with _scoped_session(factory, org) as db:
        lease = lease_cleanup(db)
    if lease is None:
        return False
    try:
        if not lease["storage_key"].startswith(tenant_prefix(org)):
            raise ValueError("Cleanup object does not belong to organization")
        # Keep the checked cleanup and deleted-job rows locked through R2 I/O.
        # Uploads use fresh immutable keys and never attach existing keys to jobs.
        with _scoped_session(factory, org) as db:
            if not db.scalar(text("SELECT public.reink_cleanup_is_safe(:id, :token)"),
                             {"id": lease["cleanup_id"], "token": lease["token"]}):
                raise ValueError("Cleanup item is not safe to delete")
            storage.delete(lease["storage_key"])
    except Exception:
        with _scoped_session(factory, org) as db:
            finish_cleanup(db, lease, False)
        return True
    with _scoped_session(factory, org) as db:
        db.scalar(text("SELECT public.reink_finish_storage_cleanup(:id, :token)"),
                  {"id": lease["cleanup_id"], "token": lease["token"]})
    return True
