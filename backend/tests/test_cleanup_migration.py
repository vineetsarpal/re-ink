"""Migration rollback preserves the prior function body and security settings."""
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url

from conftest import TEST_DATABASE_URL


def test_cleanup_migration_roundtrip_preserves_function_and_acl():
    parsed = make_url(TEST_DATABASE_URL)
    assert parsed.host in {"localhost", "127.0.0.1"}, "Migration test requires local PostgreSQL"
    name = "reink_migration_" + uuid4().hex
    admin_url = parsed.set(database="postgres").render_as_string(hide_password=False)
    url = parsed.set(database=name).render_as_string(hide_password=False)
    root = Path(__file__).resolve().parents[1]
    env = {**os.environ, "DATABASE_URL": url}

    def migrate(*args):
        result = subprocess.run([sys.executable, "-m", "alembic", *args], cwd=root, env=env, capture_output=True, text=True)
        assert result.returncode == 0, result.stdout + result.stderr

    def function():
        with psycopg.connect(url) as db:
            return db.execute("SELECT pg_get_functiondef(oid), proacl::text, proconfig, prosecdef FROM pg_proc WHERE oid='public.reink_finish_expired_upload(varchar,varchar,boolean)'::regprocedure").fetchone()

    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        try:
            migrate("upgrade", "0015_trial_hardening")
            before = function()
            assert before[2] == ['search_path=pg_catalog, pg_temp']
            assert before[3] is True
            migrate("upgrade", "head")
            upgraded = function()
            assert upgraded[1:] == before[1:]
            migrate("downgrade", "0015_trial_hardening")
            assert function() == before
            migrate("upgrade", "head")
            assert function() == upgraded
        finally:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
