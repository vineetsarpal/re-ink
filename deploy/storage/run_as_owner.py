"""Run one command with DATABASE_URL set from a hidden prompt.

Run from backend/, e.g.:
    python ../deploy/storage/run_as_owner.py --target validation python -m alembic upgrade head
    python ../deploy/storage/run_as_owner.py --target production python ../deploy/storage/provision_expiry.py reink_cf_expiry

The URL is never echoed, logged, or written to disk; it only reaches the child
process environment. You must confirm the endpoint ID before anything runs.
"""
import getpass
import os
import subprocess
import sys

from psycopg.conninfo import conninfo_to_dict

EXPECTED_DB = "reink_db"
PRODUCTION_ENDPOINT = "ep-small-paper-aek1bh55"


def main() -> int:
    if len(sys.argv) < 4 or sys.argv[1] != "--target" or sys.argv[2] not in ("production", "validation"):
        raise SystemExit(__doc__)
    target, command = sys.argv[2], sys.argv[3:]
    url = getpass.getpass("Direct owner connection URL (hidden): ").strip()
    params = conninfo_to_dict(url)
    host = params.get("host", "")
    if "-pooler" in host:
        raise SystemExit("Use the direct (non-pooler) endpoint")
    if params.get("dbname") != EXPECTED_DB:
        raise SystemExit(f"Database must be {EXPECTED_DB}")
    endpoint = host.split(".")[0]
    if (endpoint == PRODUCTION_ENDPOINT) != (target == "production"):
        actual = "production" if endpoint == PRODUCTION_ENDPOINT else "a non-production"
        raise SystemExit(f"--target {target} but {endpoint} is {actual} endpoint; nothing ran")
    print(f"Target {target.upper()}: endpoint {endpoint}, database {EXPECTED_DB}")
    print(f"Command: {' '.join(command)}")
    if input("Type the endpoint ID again to confirm: ").strip() != endpoint:
        raise SystemExit("Confirmation did not match; nothing ran")
    env = dict(os.environ, DATABASE_URL=url)
    return subprocess.run(command, env=env).returncode


if __name__ == "__main__":
    sys.exit(main())
