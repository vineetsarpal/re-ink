"""Diagnose service-role logins using passwords from the macOS Keychain.

Prompts (hidden) for the owner URL only to learn host/port/dbname; the owner
credentials are not used. Prints libpq error text, never passwords.
"""
import getpass
import subprocess

import certifi
import psycopg
from psycopg.conninfo import conninfo_to_dict, make_conninfo

ROLES = ("reink_cf_machine", "reink_cf_dispatch", "reink_cf_expiry", "reink_cf_cleanup", "reink_cf_purge")
KEYCHAIN_SERVICE = "re-ink neon production reink_db"
VARIANTS = {
    "verify-full/system": {"sslmode": "verify-full", "sslrootcert": "system"},
    "verify-full/certifi": {"sslmode": "verify-full", "sslrootcert": certifi.where()},
    "require": {"sslmode": "require"},
}


def main() -> None:
    params = conninfo_to_dict(getpass.getpass("Direct owner connection URL (hidden; only host/db are used): ").strip())
    target = {k: params[k] for k in ("host", "port", "dbname") if k in params}
    print(f"Target endpoint {target['host'].split('.')[0]}, database {target.get('dbname')}")
    for role in ROLES:
        password = subprocess.run(["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", role, "-w"],
                                  capture_output=True, text=True).stdout.rstrip("\n")
        if not password:
            print(f"{role}: no Keychain entry")
            continue
        for name, tls in VARIANTS.items():
            try:
                with psycopg.connect(make_conninfo(**target, user=role, password=password, **tls), connect_timeout=10) as conn:
                    print(f"{role} [{name}]: OK as {conn.execute('SELECT current_user').fetchone()[0]}")
            except Exception as exc:
                message = " ".join(str(exc).split()).replace(password, "***")
                print(f"{role} [{name}]: {type(exc).__name__}: {message[:300]}")


if __name__ == "__main__":
    main()
