"""Run inside actual VPS runtime. All probe transactions roll back; no live mutation.
Requires a dedicated provisioned worker and explicit alternate-tenant probe name.
"""
import argparse
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
from app.core.config import settings

TABLES = ("extraction_jobs", "extraction_attempts", "workflow_outbox", "workflow_receipts", "storage_cleanup")


def check(url, org, other_org, local_test=False):
    params = conninfo_to_dict(url)
    if not local_test and params.get("sslmode") != "verify-full":
        raise RuntimeError("Worker requires hostname-verifying TLS")
    if not org or not other_org or org == other_org:
        raise RuntimeError("Two distinct explicit tenant probe scopes are required")
    with psycopg.connect(url) as conn:
        role = conn.execute("SELECT current_user").fetchone()[0]
        flags = conn.execute("SELECT rolsuper,rolbypassrls,rolcreaterole,rolcreatedb FROM pg_roles WHERE rolname=current_user").fetchone()
        if any(flags):
            raise RuntimeError("Worker role is privileged")
        if conn.execute("SELECT 1 FROM pg_class WHERE relowner=(SELECT oid FROM pg_roles WHERE rolname=current_user)").fetchone():
            raise RuntimeError("Worker owns relations")
        if conn.execute("SELECT 1 FROM pg_auth_members WHERE member=(SELECT oid FROM pg_roles WHERE rolname=current_user)").fetchone():
            raise RuntimeError("Worker inherits another role")
        for table in ("contracts", "parties"):
            for permission in ("INSERT", "UPDATE", "DELETE"):
                if conn.execute("SELECT has_table_privilege(current_user,%s,%s)", (table, permission)).fetchone()[0]:
                    raise RuntimeError("Worker has approval table writes")
        conn.execute("SELECT set_config('app.current_org',%s,true)", (org,))
        conn.execute("SET LOCAL lock_timeout='2s'")
        conn.execute("SET LOCAL statement_timeout='10s'")
        for table in TABLES:
            policies = conn.execute("SELECT qual,with_check FROM pg_policies WHERE schemaname='public' AND tablename=%s AND policyname=%s AND permissive='RESTRICTIVE' AND %s=ANY(roles)", (table, "worker_scope_" + role, role)).fetchall()
            # Match the provisioning script's exact server-rendered literal predicate,
            # rather than accepting a different policy whose text happens to mention org.
            expected = conn.execute(sql.SQL("SELECT pg_get_expr(polqual,polrelid),pg_get_expr(polwithcheck,polrelid) FROM pg_policy WHERE polname=%s AND polrelid=%s::regclass"), ("worker_scope_" + role, table)).fetchone()
            literal = conn.execute("SELECT quote_literal(%s::text)", (org,)).fetchone()[0]
            allowed = {f"(org_id = {literal}::text)", f"((org_id)::text = {literal}::text)"}
            if not policies or not expected or expected[0] not in allowed or expected[1] not in allowed:
                raise RuntimeError("Missing literal worker tenant restriction")
            # A non-owner, non-BYPASSRLS worker is subject to ENABLE RLS.
            # FORCE is an owner control and is not required by these migrations.
            if not conn.execute("SELECT relrowsecurity FROM pg_class WHERE oid=%s::regclass", (table,)).fetchone()[0]:
                raise RuntimeError("Worker table RLS is not enabled")
            conn.execute(sql.SQL("SELECT * FROM {} LIMIT 1 FOR UPDATE SKIP LOCKED").format(sql.Identifier(table))).fetchall()
        # Actual lease-style update, always rolled back. No row is required for a fresh DB.
        conn.execute("UPDATE workflow_outbox SET lease_token='access-probe',lease_until=clock_timestamp()+interval '60 seconds' WHERE attempt_id IN (SELECT attempt_id FROM workflow_outbox WHERE acknowledged_at IS NULL LIMIT 1 FOR UPDATE SKIP LOCKED)")
        conn.rollback()
        conn.execute("SELECT set_config('app.current_org',%s,true)", (other_org,))
        for table in TABLES:
            if conn.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table))).fetchone()[0]:
                raise RuntimeError("Worker can see another tenant after GUC substitution")
            changed = conn.execute(sql.SQL("UPDATE {} SET org_id=org_id").format(sql.Identifier(table)))
            if changed.rowcount:
                raise RuntimeError("Worker can mutate another tenant")
        conn.rollback()
    print("Worker role, tenant fence and rolled-back lease checks passed" + (" (local TLS gate excluded)" if local_test else " over verify-full TLS"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--other-org", required=True)
    parser.add_argument("--local-test", action="store_true", help="Disposable PostgreSQL only; does not pass deployment TLS gate")
    args = parser.parse_args()
    try:
        check(settings.WORKFLOW_WORKER_DATABASE_URL, settings.WORKFLOW_CUSTOMER_ORG_ID, args.other_org, args.local_test)
    except Exception:
        raise SystemExit("Worker access check failed; inspect protected runtime configuration and database grants")
