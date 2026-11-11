"""Grant a tenant-scoped purge identity only data deletion and lifecycle progress."""
from alembic import op

revision = '0021_purge_role'
down_revision = '0020_organization_lifecycle'
branch_labels = depends_on = None

TABLES = ('contract_parties', 'cloudflare_executions', 'workflow_receipts', 'workflow_outbox',
    'extraction_attempts', 'storage_cleanup', 'upload_intents', 'extraction_jobs',
    'contracts', 'parties', 'provider_acknowledgments', 'provider_credentials', 'provisioning_intents')


def upgrade():
    grants = ' '.join(f'GRANT SELECT (org_id), DELETE ON public.{table} TO reink_cf_purge;' for table in TABLES)
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'reink_cf_purge') THEN
            GRANT USAGE ON SCHEMA public TO reink_cf_purge;
            GRANT SELECT ON public.organization_lifecycle TO reink_cf_purge;
            GRANT UPDATE (status, purge_step, purge_attempts, last_purge_error)
                ON public.organization_lifecycle TO reink_cf_purge;
    """ + grants + ' END IF; END $$')


def downgrade():
    revoke = ' '.join(f'REVOKE SELECT (org_id), DELETE ON public.{table} FROM reink_cf_purge;' for table in TABLES)
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'reink_cf_purge') THEN
            REVOKE SELECT, UPDATE (status, purge_step, purge_attempts, last_purge_error)
                ON public.organization_lifecycle FROM reink_cf_purge;
    """ + revoke + ' END IF; END $$')
