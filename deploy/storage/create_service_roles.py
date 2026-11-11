"""Create the restricted service login roles with no table grants.

Run interactively in your own terminal (never paste the owner URL into chat):
    python deploy/storage/create_service_roles.py

Prompts for a DIRECT (non-pooler) owner connection URL, asks you to confirm
the endpoint, creates each role with a random password and stores the
password in the macOS login Keychain. Neon only accepts plaintext passwords
in CREATE ROLE, so the password travels over the TLS connection and is hashed
server-side. Grants are applied separately by provision_*.py.
"""
import argparse
import getpass
import secrets
import subprocess
import sys

import certifi
import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

ROLES = ("reink_cf_machine", "reink_cf_dispatch", "reink_cf_expiry", "reink_cf_cleanup", "reink_cf_purge")
KEYCHAIN_SERVICE = "re-ink neon production reink_db"
EXPECTED_DB = "reink_db"


def keychain_has(role: str) -> bool:
    return subprocess.run(["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", role],
                          capture_output=True).returncode == 0


def keychain_store(role: str, password: str) -> None:
    # Fed via stdin so the password never appears in a process argument list.
    command = f'add-generic-password -s "{KEYCHAIN_SERVICE}" -a "{role}" -w "{password}"\n'
    result = subprocess.run(["security", "-i"], input=command, text=True, capture_output=True)
    if result.returncode != 0 or not keychain_has(role):
        raise RuntimeError(f"Could not store {role} in Keychain")


def keychain_remove_all() -> None:
    for role in ROLES:
        subprocess.run(["security", "delete-generic-password", "-s", KEYCHAIN_SERVICE, "-a", role],
                       capture_output=True)


def main() -> None:
    global ROLES
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--role', choices=ROLES)
    args = parser.parse_args()
    if args.role:
        ROLES = (args.role,)
    owner_url = getpass.getpass("Direct owner connection URL for production reink_db (hidden): ").strip()
    params = conninfo_to_dict(owner_url)
    host = params.get("host", "")
    if "-pooler" in host:
        raise SystemExit("Use the direct (non-pooler) endpoint for role management")
    if params.get("dbname") != EXPECTED_DB:
        raise SystemExit(f"Database must be {EXPECTED_DB}")
    endpoint = host.split(".")[0]
    print(f"Connecting to endpoint {endpoint} database {EXPECTED_DB}")
    typed = input("Type the endpoint ID (starts with ep-) of the Neon *production* branch to confirm: ").strip()
    if typed != endpoint:
        hint = " (that looks like a branch ID; the endpoint ID starts with ep-)" if typed.startswith("br-") else ""
        raise SystemExit(f"Endpoint confirmation did not match{hint}; nothing changed")

    for role in ROLES:
        if keychain_has(role):
            raise SystemExit(f"Keychain already has an entry for {role}; refusing to overwrite")

    with psycopg.connect(owner_url, autocommit=True) as conn:
        head = conn.execute("SELECT version_num FROM alembic_version").fetchone()
        print(f"Schema revision: {head[0] if head else 'none'}")
        existing = [r for (r,) in conn.execute("SELECT rolname FROM pg_roles WHERE rolname = ANY(%s)", (list(ROLES),))]
        if existing:
            raise SystemExit(f"Roles already exist, not modifying: {', '.join(existing)}")

        passwords = {role: secrets.token_urlsafe(32) for role in ROLES}
        try:
            for role, password in passwords.items():
                keychain_store(role, password)
            # autocommit=True makes this a real BEGIN/COMMIT, so leaving the block means committed.
            with conn.transaction():
                for role, password in passwords.items():
                    conn.execute(sql.SQL(
                        "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT "
                        "NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 10 PASSWORD {}"
                    ).format(sql.Identifier(role), sql.Literal(password)))
        except BaseException:
            keychain_remove_all()
            print("Role creation failed and was rolled back; Keychain entries from this run were removed")
            raise
        print("Roles created and committed")

        for role in ROLES:
            flags = conn.execute("""SELECT rolsuper, rolbypassrls, rolcreaterole, rolcreatedb, rolreplication
                FROM pg_roles WHERE rolname=%s""", (role,)).fetchone()
            member_of = conn.execute("""SELECT count(*) FROM pg_auth_members
                WHERE member=(SELECT oid FROM pg_roles WHERE rolname=%s)""", (role,)).fetchone()[0]
            table_privs = conn.execute("""SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                WHERE n.nspname='public' AND c.relkind IN ('r','p','v','m','S')
                AND (has_table_privilege(%s,c.oid,'SELECT') OR has_table_privilege(%s,c.oid,'INSERT')
                  OR has_table_privilege(%s,c.oid,'UPDATE') OR has_table_privilege(%s,c.oid,'DELETE'))""",
                (role,) * 4).fetchone()[0]
            ok = flags is not None and not any(flags) and member_of == 0 and table_privs == 0
            print(f"{role}: exists={flags is not None} privileged_flags={bool(flags and any(flags))} "
                  f"memberships={member_of} table_privileges={table_privs} {'OK' if ok else 'CHECK'}")

    for role, password in passwords.items():
        role_params = dict(params, user=role, password=password, sslmode="verify-full", sslrootcert=certifi.where())
        try:
            with psycopg.connect(make_conninfo(**role_params), connect_timeout=10) as conn:
                who = conn.execute("SELECT current_user").fetchone()[0]
            print(f"{role}: login verified as {who} (verify-full TLS)")
        except Exception as exc:
            print(f"{role}: login check FAILED ({type(exc).__name__}: {' '.join(str(exc).split()).replace(password, '***')[:300]})")
    print(f"Passwords are in the macOS login Keychain under service '{KEYCHAIN_SERVICE}'.")


if __name__ == "__main__":
    sys.exit(main())
