from time import monotonic

from sqlalchemy import select, text
from workos._errors import NotFoundError

from app.core.tenancy import bind_session_to_org
from app.models.organization_lifecycle import OrganizationLifecycle
from app.services.storage_service import tenant_prefix
from app.services.workflow_service import now

DELETE_TABLES = (
    'contract_parties', 'cloudflare_executions', 'workflow_receipts', 'workflow_outbox',
    'extraction_attempts', 'storage_cleanup', 'upload_intents', 'extraction_jobs',
    'contracts', 'parties', 'provider_acknowledgments', 'provider_credentials', 'provisioning_intents',
)
RETAIN_TABLES = frozenset(('organization_lifecycle', 'extraction_quota_org',
    'extraction_quota_reservations', 'extraction_rate_org', 'trial_users', 'trial_domains'))
ORG_TABLES_SQL = """SELECT c.relname FROM pg_catalog.pg_class c
    JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
    JOIN pg_catalog.pg_attribute a ON a.attrelid=c.oid
    WHERE n.nspname='public' AND c.relkind IN ('r','p')
    AND a.attname='org_id' AND NOT a.attisdropped"""


def _lock(db, org_id):
    db.execute(text("SET LOCAL statement_timeout = '3s'"))
    acquired = db.scalar(text('SELECT pg_try_advisory_xact_lock(hashtextextended(:key, 0))'),
                         {'key': f'reink:lifecycle:{org_id}'})
    return db.get(OrganizationLifecycle, org_id, populate_existing=True) if acquired else None


def _delete_tenant_rows(db, org_id, deadline):
    tables = set(db.scalars(text(ORG_TABLES_SQL)))
    if tables != set(DELETE_TABLES) | RETAIN_TABLES:
        raise RuntimeError('Unclassified tenant schema')
    bind_session_to_org(db, org_id)
    for table in DELETE_TABLES:
        if monotonic() >= deadline:
            raise TimeoutError('Purge budget exhausted')
        db.execute(text(f'DELETE FROM public.{table} WHERE org_id = :org'), {'org': org_id})


def purge_organization(factory, storage, workos_factory, org_id, deadline):
    with factory() as db:
        row = _lock(db, org_id)
        if not row or row.status != 'closing' or row.purge_after > now(db):
            return False
        row.purge_attempts += 1
        if row.purge_step is None:
            row.purge_step = 'started'
        db.commit()
    while monotonic() < deadline:
        with factory() as db:
            row = _lock(db, org_id)
            if not row or row.status != 'closing' or row.purge_after > now(db):
                return True
            step = row.purge_step
            try:
                if step == 'started':
                    prefix = tenant_prefix(org_id)
                    for key, _ in storage.list_objects(org_id):
                        if not key.startswith(prefix):
                            raise RuntimeError('Storage escaped organization prefix')
                        if monotonic() >= deadline:
                            raise TimeoutError('Purge budget exhausted')
                        storage.delete(key)
                    if next(iter(storage.list_objects(org_id)), None) is not None:
                        raise RuntimeError('Storage verification not empty')
                    row.purge_step = 'storage_done'
                elif step == 'storage_done':
                    _delete_tenant_rows(db, org_id, deadline)
                    row.purge_step = 'data_done'
                elif step == 'data_done':
                    try:
                        workos_factory().organizations.delete_organization(org_id)
                    except NotFoundError:
                        pass
                    row.purge_step = 'workos_done'
                elif step == 'workos_done':
                    row.status = 'purged'
                    row.purge_step = 'done'
                else:
                    raise RuntimeError('Unknown purge step')
                row.last_purge_error = None
                db.commit()
                if step == 'workos_done':
                    return True
            except Exception as error:
                db.rollback()
                row = _lock(db, org_id)
                if row:
                    row.last_purge_error = f'{step}: {type(error).__name__}'
                    db.commit()
                return True
    return True


def purge_due(factory, storage, workos_factory, batch_limit, deadline):
    with factory() as db:
        db.execute(text("SET LOCAL statement_timeout = '3s'"))
        candidates = db.scalars(select(OrganizationLifecycle.org_id).where(
            OrganizationLifecycle.status == 'closing', OrganizationLifecycle.purge_after <= now(db))
            .order_by(OrganizationLifecycle.purge_attempts, OrganizationLifecycle.purge_after, OrganizationLifecycle.org_id)
            .limit(batch_limit)).all()
    processed = 0
    for org_id in candidates:
        if monotonic() >= deadline:
            break
        processed += int(purge_organization(factory, storage, workos_factory, org_id, deadline))
    return processed
