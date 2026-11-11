"""Grant a dedicated, fresh DB role queue-dispatch privileges.

Run as the schema owner from backend: python ../deploy/storage/provision_cloudflare_dispatch.py ROLE.
This role can bind any tenant for maintenance and must never be shared with
browser-facing application users. Its login secret is managed separately.
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
    flags = conn.execute("SELECT rolsuper, rolbypassrls, rolcreaterole, rolcreatedb FROM pg_roles WHERE rolname = %s", (args.role,)).fetchone()
    if not flags or any(flags):
        raise SystemExit("Dispatch role must exist without privileged role flags")
    if conn.execute("SELECT 1 FROM pg_auth_members WHERE member=(SELECT oid FROM pg_roles WHERE rolname=%s)", (args.role,)).fetchone():
        raise SystemExit("Dispatch role must have no role memberships")
    if conn.execute("SELECT 1 FROM pg_class WHERE relowner=(SELECT oid FROM pg_roles WHERE rolname=%s)", (args.role,)).fetchone():
        raise SystemExit("Dispatch role must not own relations")
    if conn.execute("""SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='public' AND c.relkind IN ('r','p','v','m','S')
        AND (has_table_privilege(%s,c.oid,'SELECT') OR has_table_privilege(%s,c.oid,'INSERT')
             OR has_table_privilege(%s,c.oid,'UPDATE') OR has_table_privilege(%s,c.oid,'DELETE')) LIMIT 1""", (args.role,) * 4).fetchone():
        raise SystemExit("Dispatch role must not have existing table privileges")
    if conn.execute("""SELECT 1 FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid
        JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='public' AND c.relkind IN ('r','p','v','m')
        AND a.attnum > 0 AND NOT a.attisdropped
        AND (has_column_privilege(%s,c.oid,a.attnum,'SELECT')
          OR has_column_privilege(%s,c.oid,a.attnum,'INSERT')
          OR has_column_privilege(%s,c.oid,a.attnum,'UPDATE')
          OR has_column_privilege(%s,c.oid,a.attnum,'REFERENCES')) LIMIT 1""", (args.role,) * 4).fetchone():
        raise SystemExit("Dispatch role must not have existing column privileges")
    conn.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(role))
    conn.execute(sql.SQL("GRANT EXECUTE ON FUNCTION public.reink_next_due_dispatch_org() TO {}").format(role))
    for table, columns in {
        "workflow_outbox": ("attempt_id", "org_id", "payload", "next_delivery_at", "lease_token", "lease_until", "delivery_count", "acknowledged_at", "last_error"),
        "extraction_jobs": ("job_id", "deleted_at", "selected_attempt_id"),
        "extraction_attempts": ("attempt_id", "job_id", "status", "deadline_at"),
    }.items():
        conn.execute(sql.SQL("GRANT SELECT ({}) ON public.{} TO {}").format(
            sql.SQL(", ").join(map(sql.Identifier, columns)), sql.Identifier(table), role))
    for table, columns in {
        "workflow_outbox": ("lease_token", "lease_until", "delivery_count", "acknowledged_at", "next_delivery_at", "last_error"),
    }.items():
        conn.execute(sql.SQL("GRANT UPDATE ({}) ON public.{} TO {}").format(
            sql.SQL(", ").join(map(sql.Identifier, columns)), sql.Identifier(table), role))
print("Cloudflare dispatch discovery and narrowly scoped lifecycle grants installed")
