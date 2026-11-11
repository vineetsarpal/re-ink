"""Grant a fresh role only the rights needed for multi-tenant R2 cleanup.

Run from backend as schema owner: python ../deploy/storage/provision_cleanup.py ROLE.
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
        raise SystemExit("Cleanup role must exist without privileged role flags")
    if conn.execute("SELECT 1 FROM pg_auth_members WHERE member=(SELECT oid FROM pg_roles WHERE rolname=%s)", (args.role,)).fetchone():
        raise SystemExit("Cleanup role must have no role memberships")
    if conn.execute("SELECT 1 FROM pg_class WHERE relowner=(SELECT oid FROM pg_roles WHERE rolname=%s)", (args.role,)).fetchone():
        raise SystemExit("Cleanup role must not own relations")
    if conn.execute("""SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='public' AND c.relkind IN ('r','p','v','m','S')
        AND (has_table_privilege(%s,c.oid,'SELECT') OR has_table_privilege(%s,c.oid,'INSERT')
          OR has_table_privilege(%s,c.oid,'UPDATE') OR has_table_privilege(%s,c.oid,'DELETE')) LIMIT 1""", (args.role,) * 4).fetchone():
        raise SystemExit("Cleanup role must not have existing table privileges")
    if conn.execute("""SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='public' AND c.relkind IN ('r','p','v','m')
        AND (has_any_column_privilege(%s,c.oid,'SELECT') OR has_any_column_privilege(%s,c.oid,'INSERT')
          OR has_any_column_privilege(%s,c.oid,'UPDATE') OR has_any_column_privilege(%s,c.oid,'REFERENCES')) LIMIT 1""", (args.role,) * 4).fetchone():
        raise SystemExit("Cleanup role must not have existing column privileges")
    conn.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(role))
    conn.execute(sql.SQL("GRANT EXECUTE ON FUNCTION public.reink_next_cleanup_org() TO {}").format(role))
    conn.execute(sql.SQL("GRANT EXECUTE ON FUNCTION public.reink_finish_storage_cleanup(varchar, varchar) TO {}").format(role))
    conn.execute(sql.SQL("GRANT EXECUTE ON FUNCTION public.reink_cleanup_is_safe(varchar, varchar) TO {}").format(role))
    for signature in ('reink_cleanup_upload_first()', 'reink_lease_expired_upload(varchar)',
                      'reink_expired_upload_is_safe(varchar, varchar)', 'reink_finish_expired_upload(varchar, varchar, boolean)'):
        conn.execute(sql.SQL('GRANT EXECUTE ON FUNCTION public.{} TO {}').format(sql.SQL(signature), role))
    conn.execute(sql.SQL("GRANT SELECT ON public.storage_cleanup TO {}").format(role))
    conn.execute(sql.SQL("GRANT UPDATE (attempts, lease_token, lease_until, next_attempt_at) ON public.storage_cleanup TO {}").format(role))
print("Cleanup discovery and narrow lifecycle grants installed")
