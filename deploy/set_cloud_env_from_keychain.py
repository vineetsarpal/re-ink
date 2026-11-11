"""Set trial secrets on FastAPI Cloud from the macOS Keychain. Prints names only.

Usage (from the directory linked to the FastAPI Cloud app):
    python set_cloud_env_from_keychain.py --dry-run
    python set_cloud_env_from_keychain.py
Refuses to overwrite variables that already exist.
"""
import subprocess
import sys
from urllib.parse import quote

from fastapi_cloud_cli.commands.env import _get_environment_variables, _set_environment_variable
from fastapi_cloud_cli.utils.apps import get_app_config
from pathlib import Path

TRIAL_SERVICE = "re-ink production trial"
ROLE_SERVICE = "re-ink neon production reink_db"
DIRECT_HOST = "ep-small-paper-aek1bh55.c-2.us-east-2.aws.neon.tech"
DATABASE = "reink_db"
TRIAL_SECRETS = ("CLOUDFLARE_MACHINE_TOKEN", "CLOUDFLARE_DISPATCH_TOKEN", "CLOUDFLARE_EXPIRY_TOKEN",
                 "CLOUDFLARE_CLEANUP_TOKEN", "CLOUDFLARE_PURGE_TOKEN", "CLOUDFLARE_CAPABILITY_KEY", "PROVIDER_CREDENTIAL_ENCRYPTION_KEY")
ROLE_URLS = {"CLOUDFLARE_MACHINE_DATABASE_URL": "reink_cf_machine",
             "CLOUDFLARE_DISPATCH_DATABASE_URL": "reink_cf_dispatch",
             "CLOUDFLARE_EXPIRY_DATABASE_URL": "reink_cf_expiry",
             "CLOUDFLARE_CLEANUP_DATABASE_URL": "reink_cf_cleanup",
             "CLOUDFLARE_PURGE_DATABASE_URL": "reink_cf_purge"}


def keychain(service: str, account: str) -> str:
    value = subprocess.run(["security", "find-generic-password", "-s", service, "-a", account, "-w"],
                           capture_output=True, text=True).stdout.rstrip("\n")
    if not value:
        raise SystemExit(f"Missing Keychain entry {service} / {account}")
    return value


def main() -> None:
    dry_run = "--dry-run" in sys.argv
    app_id = get_app_config(Path.cwd()).app_id
    existing = {v.name for v in _get_environment_variables(app_id).data}
    values = {name: keychain(TRIAL_SERVICE, name) for name in TRIAL_SECRETS}
    for name, role in ROLE_URLS.items():
        password = quote(keychain(ROLE_SERVICE, role), safe="")
        values[name] = f"postgresql://{role}:{password}@{DIRECT_HOST}/{DATABASE}?sslmode=verify-full"
    clash = sorted(set(values) & existing)
    if clash:
        raise SystemExit(f"Already set, not overwriting: {clash}")
    for name, value in values.items():
        if dry_run:
            print(f"would set secret {name} ({len(value)} chars)")
        else:
            _set_environment_variable(app_id, name, value, is_secret=True)
            print(f"set secret {name}")


if __name__ == "__main__":
    main()
