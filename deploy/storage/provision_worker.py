"""Owner-only worker grant setup. Existing role login secret is managed externally.
Run from backend with migration DATABASE_URL, WORKFLOW_CUSTOMER_ORG_ID and role arg.
"""
import argparse
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
import psycopg
from psycopg import sql
from app.core.config import settings

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("role", help="Existing dedicated LOGIN role, never the migration/app role")
args = parser.parse_args()
org = settings.WORKFLOW_CUSTOMER_ORG_ID
if not org:
    parser.error("Customer scope required")
tables = ("extraction_jobs", "extraction_attempts", "workflow_outbox", "workflow_receipts", "storage_cleanup")
with psycopg.connect(settings.DATABASE_URL.replace("postgresql+psycopg://", "postgresql://")) as conn:
    row = conn.execute("SELECT rolsuper, rolbypassrls, rolcreaterole, rolcreatedb FROM pg_roles WHERE rolname = %s", (args.role,)).fetchone()
    if not row or any(row):
        raise SystemExit("Worker role must exist without privileged role flags")
    if conn.execute("SELECT 1 FROM pg_auth_members JOIN pg_roles ON roleid=pg_roles.oid WHERE member=(SELECT oid FROM pg_roles WHERE rolname=%s)", (args.role,)).fetchone():
        raise SystemExit("Worker must have no role memberships")
    if conn.execute("SELECT 1 FROM pg_class WHERE relowner=(SELECT oid FROM pg_roles WHERE rolname=%s)", (args.role,)).fetchone():
        raise SystemExit("Worker must not own relations")
    role = sql.Identifier(args.role)
    conn.execute(sql.SQL("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {}").format(role))
    conn.execute(sql.SQL("REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {}").format(role))
    conn.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(role))
    for table in tables:
        ident = sql.Identifier(table)
        conn.execute(sql.SQL("GRANT SELECT, UPDATE, DELETE ON {} TO {}").format(ident, role))
        # Lifecycle worker does not create jobs/attempts/receipts; no INSERT grant.
        policy = sql.Identifier("worker_scope_" + args.role)
        conn.execute(sql.SQL("DROP POLICY IF EXISTS {} ON {}").format(policy, ident))
        conn.execute(sql.SQL("CREATE POLICY {} ON {} AS RESTRICTIVE FOR ALL TO {} USING (org_id = {}) WITH CHECK (org_id = {})").format(policy, ident, role, sql.Literal(org), sql.Literal(org)))
print("Restricted worker grants and literal tenant policies installed; run access checks separately")
