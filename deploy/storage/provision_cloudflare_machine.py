"""Grant a fresh dedicated PostgreSQL role Cloudflare extraction privileges.

Run as schema owner: python ../deploy/storage/provision_cloudflare_machine.py ROLE.
This role can scope itself to any tenant and read encrypted attempt snapshots
and pending results. It must not be shared with application users.
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
        raise SystemExit("Machine role must exist without privileged role flags")
    if conn.execute("SELECT 1 FROM pg_auth_members WHERE member=(SELECT oid FROM pg_roles WHERE rolname=%s)", (args.role,)).fetchone():
        raise SystemExit("Machine role must have no role memberships")
    if conn.execute("SELECT 1 FROM pg_class WHERE relowner=(SELECT oid FROM pg_roles WHERE rolname=%s)", (args.role,)).fetchone():
        raise SystemExit("Machine role must not own relations")
    if conn.execute("""SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='public' AND c.relkind IN ('r','p','v','m','S')
        AND (has_table_privilege(%s,c.oid,'SELECT') OR has_table_privilege(%s,c.oid,'INSERT')
             OR has_table_privilege(%s,c.oid,'UPDATE') OR has_table_privilege(%s,c.oid,'DELETE')) LIMIT 1""", (args.role,) * 4).fetchone():
        raise SystemExit("Machine role must not have existing table privileges")
    if conn.execute("""SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='public' AND c.relkind IN ('r','p','v','m')
        AND (has_any_column_privilege(%s,c.oid,'SELECT') OR has_any_column_privilege(%s,c.oid,'INSERT')
          OR has_any_column_privilege(%s,c.oid,'UPDATE') OR has_any_column_privilege(%s,c.oid,'REFERENCES')) LIMIT 1""", (args.role,) * 4).fetchone():
        raise SystemExit("Machine role must not have existing column privileges")
    conn.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(role))
    columns = {
        "extraction_jobs": ("job_id", "org_id", "selected_attempt_id", "deleted_at", "status", "error", "message", "failed_at", "completed_at", "filename", "storage_key", "size_bytes", "sha256", "content_type"),
    }
    for table, names in columns.items():
        conn.execute(sql.SQL("GRANT SELECT ({}) ON public.{} TO {}").format(
            sql.SQL(", ").join(map(sql.Identifier, names)), sql.Identifier(table), role))
    for table in ("extraction_attempts", "workflow_outbox", "workflow_receipts", "cloudflare_executions", "extraction_quota_global", "extraction_quota_org", "extraction_quota_reservations"):
        conn.execute(sql.SQL("GRANT SELECT ON public.{} TO {}").format(sql.Identifier(table), role))
    for table, names in {
        "extraction_jobs": ("status", "error", "message", "failed_at", "completed_at", "parsed_results"),
        "extraction_attempts": ("status", "accepted_at", "deadline_at", "execution_key", "completed_at", "error_code", "error_message", "workflow_execution_id"),
        "workflow_outbox": ("acknowledged_at", "lease_token", "lease_until"),
        "cloudflare_executions": ("terminal_event",),
        "extraction_quota_global": ("month", "trial_successes", "trial_pending", "trial_starts"),
        "extraction_quota_org": ("month", "monthly_successes", "monthly_attempts", "pending", "free_successes", "free_pending"),
        "extraction_quota_reservations": ("status", "credential_snapshot", "provider_started"),
    }.items():
        conn.execute(sql.SQL("GRANT UPDATE ({}) ON public.{} TO {}").format(
            sql.SQL(", ").join(map(sql.Identifier, names)), sql.Identifier(table), role))
    for table in ("cloudflare_executions", "workflow_receipts", "extraction_quota_global", "extraction_quota_org"):
        conn.execute(sql.SQL("GRANT INSERT ON public.{} TO {}").format(sql.Identifier(table), role))
print("Cloudflare machine lifecycle grants installed")
