"""Read-only listing of each service role's effective privileges. Prints no secrets."""
import os

import psycopg

ROLES = ("reink_cf_machine", "reink_cf_dispatch", "reink_cf_expiry", "reink_cf_cleanup", "reink_cf_purge")


def main() -> None:
    url = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(url) as conn:
        conn.read_only = True
        for role in ROLES:
            if not conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).fetchone():
                print(f"== {role}: absent")
                continue
            print(f"== {role}")
            tables = conn.execute("""SELECT c.relname, array_remove(ARRAY[
                    CASE WHEN has_table_privilege(%(r)s, c.oid, 'SELECT') THEN 'SELECT' END,
                    CASE WHEN has_table_privilege(%(r)s, c.oid, 'INSERT') THEN 'INSERT' END,
                    CASE WHEN has_table_privilege(%(r)s, c.oid, 'UPDATE') THEN 'UPDATE' END,
                    CASE WHEN has_table_privilege(%(r)s, c.oid, 'DELETE') THEN 'DELETE' END], NULL)
                FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public' AND c.relkind IN ('r','p','v','m','S') ORDER BY 1""", {"r": role}).fetchall()
            for name, privs in tables:
                if privs:
                    print(f"  table {name}: {','.join(privs)}")
            columns = conn.execute("""SELECT table_name, privilege_type, string_agg(column_name, ',' ORDER BY column_name)
                FROM information_schema.column_privileges WHERE grantee = %s AND table_schema = 'public'
                GROUP BY 1, 2 ORDER BY 1, 2""", (role,)).fetchall()
            for table, priv, cols in columns:
                print(f"  column {priv} {table}({cols})")
            functions = conn.execute("""SELECT p.oid::regprocedure::text FROM pg_proc p
                JOIN pg_namespace n ON n.oid = p.pronamespace
                WHERE n.nspname = 'public' AND has_function_privilege(%s, p.oid, 'EXECUTE') ORDER BY 1""", (role,)).fetchall()
            for (fn,) in functions:
                print(f"  execute {fn}")
        conn.rollback()


if __name__ == "__main__":
    main()
