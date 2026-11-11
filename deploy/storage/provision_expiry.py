"""Grant a fresh dedicated PostgreSQL role the narrow expiry-worker privileges.

Run as the schema owner from backend: python ../deploy/storage/provision_expiry.py ROLE.
The role's login secret is managed outside this script. This role can scope
itself to any organization for maintenance and must not be shared with the app.
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
        raise SystemExit("Expiry role must exist without privileged role flags")
    if conn.execute("SELECT 1 FROM pg_auth_members WHERE member=(SELECT oid FROM pg_roles WHERE rolname=%s)", (args.role,)).fetchone():
        raise SystemExit("Expiry role must have no role memberships")
    if conn.execute("SELECT 1 FROM pg_class WHERE relowner=(SELECT oid FROM pg_roles WHERE rolname=%s)", (args.role,)).fetchone():
        raise SystemExit("Expiry role must not own relations")
    if conn.execute("""SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='public' AND c.relkind IN ('r','p','v','m','S')
        AND (has_table_privilege(%s,c.oid,'SELECT') OR has_table_privilege(%s,c.oid,'INSERT')
             OR has_table_privilege(%s,c.oid,'UPDATE') OR has_table_privilege(%s,c.oid,'DELETE')) LIMIT 1""", (args.role,) * 4).fetchone():
        raise SystemExit("Expiry role must not have existing table privileges")
    if conn.execute("""SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='public' AND c.relkind IN ('r','p','v','m')
        AND (has_any_column_privilege(%s,c.oid,'SELECT') OR has_any_column_privilege(%s,c.oid,'INSERT')
             OR has_any_column_privilege(%s,c.oid,'UPDATE') OR has_any_column_privilege(%s,c.oid,'REFERENCES')) LIMIT 1""", (args.role,) * 4).fetchone():
        raise SystemExit("Expiry role must not have existing column privileges")
    conn.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(role))
    conn.execute(sql.SQL("GRANT EXECUTE ON FUNCTION public.reink_next_expired_extraction() TO {}").format(role))
    for table in ("extraction_quota_global", "extraction_quota_org"):
        conn.execute(sql.SQL("GRANT SELECT ON public.{} TO {}").format(sql.Identifier(table), role))
    for table, columns in {
        "extraction_jobs": ("job_id", "org_id", "selected_attempt_id", "deleted_at", "status", "error", "message", "failed_at"),
        "extraction_attempts": ("attempt_id", "status", "deadline_at", "accepted_at", "error_code", "error_message", "completed_at"),
        "extraction_quota_reservations": ("org_id", "attempt_id", "status", "funding"),
    }.items():
        conn.execute(sql.SQL("GRANT SELECT ({}) ON public.{} TO {}").format(
            sql.SQL(", ").join(map(sql.Identifier, columns)), sql.Identifier(table), role))
    for table, columns in {
        "extraction_jobs": ("status", "error", "message", "failed_at"),
        "extraction_attempts": ("status", "error_code", "error_message", "completed_at"),
        "extraction_quota_global": ("month", "trial_successes", "trial_pending", "trial_starts"),
        "extraction_quota_org": ("month", "monthly_successes", "monthly_attempts", "pending", "free_successes", "free_pending"),
        "extraction_quota_reservations": ("status", "credential_snapshot"),
    }.items():
        conn.execute(sql.SQL("GRANT UPDATE ({}) ON public.{} TO {}").format(
            sql.SQL(", ").join(map(sql.Identifier, columns)), sql.Identifier(table), role))
    # Existing quota services use INSERT ... ON CONFLICT for counters.
    for table in ("extraction_quota_global", "extraction_quota_org"):
        conn.execute(sql.SQL("GRANT INSERT ON public.{} TO {}").format(sql.Identifier(table), role))
print("Expiry discovery and narrowly scoped lifecycle grants installed")
