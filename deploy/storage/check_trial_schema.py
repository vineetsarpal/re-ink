"""Read-only snapshot of trial schema state. Prints no secrets.

Run via run_as_owner.py from backend/:
    python ../deploy/storage/run_as_owner.py python ../deploy/storage/check_trial_schema.py
"""
import os

import psycopg

DEFINER = """SELECT p.oid::regprocedure FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
    WHERE n.nspname = 'public' AND p.prosecdef AND p.proname LIKE 'reink\\_%'"""


def main() -> None:
    url = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(url) as conn:
        conn.read_only = True
        q = lambda s, *a: conn.execute(s, a or None).fetchall()
        print("revision:", q("SELECT version_num FROM alembic_version")[0][0])
        for table in ("contracts", "parties", "extraction_jobs", "upload_intents", "storage_cleanup", "workflow_outbox"):
            print(f"rows {table}:", q(f"SELECT count(*) FROM public.{table}")[0][0])
        print("pending outbox:", q("SELECT count(*) FROM public.workflow_outbox WHERE acknowledged_at IS NULL")[0][0])
        print("pending cleanup:", q("SELECT count(*) FROM public.storage_cleanup WHERE completed_at IS NULL")[0][0])
        print("upload intents by status:", dict(q("SELECT status, count(*) FROM public.upload_intents GROUP BY status")))
        print("upload_intents check constraints:", [r[0] for r in q(
            "SELECT conname FROM pg_constraint WHERE conrelid = 'public.upload_intents'::regclass AND contype = 'c'")])
        functions = [r[0] for r in q(DEFINER)]
        app = q("SELECT 1 FROM pg_roles WHERE rolname = 'reink_app'")
        if app:
            leaked = [f for f in functions if q("SELECT has_function_privilege('reink_app', %s::regprocedure, 'EXECUTE')", f)[0][0]]
            print(f"reink_app can execute {len(leaked)} of {len(functions)} definer functions:", leaked)
        paths = {tuple(r[0] or []) for r in q(f"SELECT proconfig FROM pg_proc WHERE oid IN ({DEFINER})")}
        print("definer search_path settings:", sorted(paths))
        for role in ("reink_cf_machine", "reink_cf_dispatch", "reink_cf_expiry", "reink_cf_cleanup", "reink_cf_purge", "reink_cf_auditor"):
            row = q("SELECT rolcanlogin, rolsuper OR rolbypassrls OR rolcreaterole OR rolcreatedb OR rolreplication "
                    "FROM pg_roles WHERE rolname = %s", role)
            print(f"role {role}:", "absent" if not row else f"login={row[0][0]} privileged={row[0][1]}")
        conn.rollback()


if __name__ == "__main__":
    main()
