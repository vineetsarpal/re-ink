"""Grant a fresh role only the rights needed for multi-tenant R2 purge.

Run from backend as schema owner: python ../deploy/storage/provision_purge.py ROLE.
The role is a privileged maintenance identity and must not be shared with users.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
import psycopg
from psycopg import sql
from app.core.config import settings

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("role")
args = parser.parse_args()
with psycopg.connect(settings.DATABASE_URL.replace("postgresql+psycopg://", "postgresql://")) as conn:
    role = sql.Identifier(args.role)
    flags = conn.execute("SELECT rolsuper, rolbypassrls, rolcreaterole, rolcreatedb FROM pg_roles WHERE rolname=%s", (args.role,)).fetchone()
    if not flags or any(flags):
        raise SystemExit("Purge role must exist without privileged role flags")
    if conn.execute("SELECT 1 FROM pg_auth_members WHERE member=(SELECT oid FROM pg_roles WHERE rolname=%s)", (args.role,)).fetchone():
        raise SystemExit("Purge role must have no role memberships")
    if conn.execute("SELECT 1 FROM pg_class WHERE relowner=(SELECT oid FROM pg_roles WHERE rolname=%s)", (args.role,)).fetchone():
        raise SystemExit("Purge role must not own relations")
    if conn.execute("""SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='public' AND c.relkind IN ('r','p','v','m','S')
        AND (has_table_privilege(%s,c.oid,'SELECT') OR has_table_privilege(%s,c.oid,'INSERT')
          OR has_table_privilege(%s,c.oid,'UPDATE') OR has_table_privilege(%s,c.oid,'DELETE')) LIMIT 1""", (args.role,) * 4).fetchone():
        raise SystemExit("Purge role must not have existing table privileges")
    if conn.execute("""SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='public' AND c.relkind IN ('r','p','v','m')
        AND (has_any_column_privilege(%s,c.oid,'SELECT') OR has_any_column_privilege(%s,c.oid,'INSERT')
          OR has_any_column_privilege(%s,c.oid,'UPDATE') OR has_any_column_privilege(%s,c.oid,'REFERENCES')) LIMIT 1""", (args.role,) * 4).fetchone():
        raise SystemExit("Purge role must not have existing column privileges")
    conn.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(role))
    tables = ('contract_parties', 'cloudflare_executions', 'workflow_receipts', 'workflow_outbox',
        'extraction_attempts', 'storage_cleanup', 'upload_intents', 'extraction_jobs',
        'contracts', 'parties', 'provider_acknowledgments', 'provider_credentials', 'provisioning_intents')
    conn.execute(sql.SQL('GRANT SELECT ON public.organization_lifecycle TO {}').format(role))
    conn.execute(sql.SQL('GRANT UPDATE (status, purge_step, purge_attempts, last_purge_error) ON public.organization_lifecycle TO {}').format(role))
    for table in tables:
        conn.execute(sql.SQL('GRANT SELECT (org_id), DELETE ON public.{} TO {}').format(sql.Identifier(table), role))
print('Tenant-scoped purge grants installed; RLS remains enforced')
