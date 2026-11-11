"""Grant a fresh role access to exact-key reference checks, with no table access.

Run as the schema owner from backend: python ../deploy/storage/provision_orphan_auditor.py ROLE
The role and login secret must already exist and be managed separately.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
import psycopg
from psycopg import sql
from app.core.config import settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("role")
    args = parser.parse_args()
    with psycopg.connect(settings.DATABASE_URL.replace("postgresql+psycopg://", "postgresql://")) as conn:
        flags = conn.execute("SELECT rolsuper, rolbypassrls, rolcreaterole, rolcreatedb FROM pg_roles WHERE rolname = %s", (args.role,)).fetchone()
        if not flags or any(flags):
            raise SystemExit("Auditor role must exist without privileged role flags")
        if conn.execute("SELECT 1 FROM pg_auth_members WHERE member=(SELECT oid FROM pg_roles WHERE rolname=%s)", (args.role,)).fetchone():
            raise SystemExit("Auditor role must have no role memberships")
        if conn.execute("SELECT 1 FROM pg_class WHERE relowner=(SELECT oid FROM pg_roles WHERE rolname=%s)", (args.role,)).fetchone():
            raise SystemExit("Auditor role must not own relations")
        if conn.execute("""SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='public' AND c.relkind IN ('r','p','v','m','S') AND
            (has_table_privilege(%s,c.oid,'SELECT') OR has_table_privilege(%s,c.oid,'INSERT') OR
             has_table_privilege(%s,c.oid,'UPDATE') OR has_table_privilege(%s,c.oid,'DELETE')) LIMIT 1""", (args.role,) * 4).fetchone():
            raise SystemExit("Auditor role must have no existing table privileges")
        if conn.execute("""SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='public' AND c.relkind IN ('r','p','v','m') AND
            (has_any_column_privilege(%s,c.oid,'SELECT') OR has_any_column_privilege(%s,c.oid,'INSERT') OR
             has_any_column_privilege(%s,c.oid,'UPDATE') OR has_any_column_privilege(%s,c.oid,'REFERENCES')) LIMIT 1""", (args.role,) * 4).fetchone():
            raise SystemExit("Auditor role must have no existing column privileges")
        role = sql.Identifier(args.role)
        conn.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(role))
        conn.execute(sql.SQL("GRANT EXECUTE ON FUNCTION public.reink_storage_key_referenced(text) TO {}").format(role))
    print("Report-only orphan auditor privileges installed")


if __name__ == "__main__":
    main()
