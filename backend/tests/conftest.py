"""
Shared Postgres test harness.

The whole tenancy guarantee lives in Postgres-only features (RLS, ``SET LOCAL``,
``current_setting``) that SQLite cannot run, so the suite runs against a real
Postgres database. This module provisions a ``reink_test`` database, applies
migrations, and hands tests an isolated, rolled-back session per test.

The test database URL defaults to a local Postgres and is overridable via
``TEST_DATABASE_URL`` (CI injects its service-container URL there).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# --- environment, set before any app import -------------------------------
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/reink_test",
)
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ.setdefault("LANDINGAI_API_KEY", "dummy-key")
os.environ.setdefault("AGENT_OFFLINE_MODE", "true")

import psycopg  # noqa: E402
import pytest  # noqa: E402
from psycopg import sql  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

# The application connects as a restricted, non-BYPASSRLS role so that the
# tenancy RLS policies (added in a later slice) actually apply to it; migrations
# run as the privileged owner. Overridable for CI.
RESTRICTED_ROLE = os.environ.get("TEST_APP_ROLE", "reink_app")
RESTRICTED_PASSWORD = os.environ.get("TEST_APP_PASSWORD", "reink_app")


def _ensure_database_exists(url: str) -> None:
    """Create the target database if it does not yet exist."""
    parsed = make_url(url)
    admin_dsn = (
        f"host={parsed.host} port={parsed.port or 5432} "
        f"user={parsed.username} password={parsed.password} dbname=postgres"
    )
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        exists = conn.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (parsed.database,)
        ).fetchone()
        if not exists:
            conn.execute(f'CREATE DATABASE "{parsed.database}"')


def _provision_restricted_role(url: str) -> None:
    """Create the restricted runtime role and grant it data access on the schema."""
    parsed = make_url(url)
    owner_dsn = (
        f"host={parsed.host} port={parsed.port or 5432} "
        f"user={parsed.username} password={parsed.password} dbname={parsed.database}"
    )
    role = sql.Identifier(RESTRICTED_ROLE)
    with psycopg.connect(owner_dsn, autocommit=True) as conn:
        exists = conn.execute(
            "SELECT 1 FROM pg_roles WHERE rolname = %s", (RESTRICTED_ROLE,)
        ).fetchone()
        if not exists:
            conn.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                    role, sql.Literal(RESTRICTED_PASSWORD)
                )
            )
        for stmt in (
            "GRANT USAGE ON SCHEMA public TO {}",
            "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {}",
            "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {}",
        ):
            conn.execute(sql.SQL(stmt).format(role))


def _restricted_url() -> str:
    """The test DB URL rewritten to connect as the restricted role (psycopg 3 driver)."""
    return make_url(TEST_DATABASE_URL).set(
        drivername="postgresql+psycopg",
        username=RESTRICTED_ROLE,
        password=RESTRICTED_PASSWORD,
    ).render_as_string(hide_password=False)


@pytest.fixture(scope="session", autouse=True)
def _provision_test_database() -> None:
    """Create the test database, migrate it, and provision the restricted role."""
    _ensure_database_exists(TEST_DATABASE_URL)

    from alembic import command
    from alembic.config import Config

    cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
    command.upgrade(cfg, "head")

    _provision_restricted_role(TEST_DATABASE_URL)


@pytest.fixture(scope="session")
def restricted_engine():
    """Engine bound to the restricted runtime role (what the app uses in prod)."""
    from sqlalchemy import create_engine

    engine = create_engine(_restricted_url(), pool_pre_ping=True)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture()
def db_session(restricted_engine):
    """An isolated session: every test runs in a transaction rolled back at teardown."""
    from sqlalchemy.orm import sessionmaker

    connection = restricted_engine.connect()
    transaction = connection.begin()
    Session = sessionmaker(bind=connection, autoflush=False, autocommit=False)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        # A failed statement (e.g. a constraint violation) may already have
        # unwound the transaction; only roll back if it is still active.
        if transaction.is_active:
            transaction.rollback()
        connection.close()


DEFAULT_TEST_ORG = "org_test_default"


@pytest.fixture()
def client(db_session):
    """A TestClient authenticated as a default org.

    Binds the per-test ``db_session`` to a default org and routes both ``get_db``
    and ``get_tenant_db`` at it, so the whole app runs org-scoped under real RLS.
    Use ``as_org`` instead when a test needs to exercise cross-org isolation.
    """
    from fastapi.testclient import TestClient

    from app.core.auth import CurrentUser, get_current_user
    from app.core.tenancy import bind_session_to_org, get_tenant_db
    from app.db.database import get_db
    from app.main import app

    bind_session_to_org(db_session, DEFAULT_TEST_ORG)

    def _get_test_db():
        yield db_session

    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user_id="test-user", org_id=DEFAULT_TEST_ORG
    )
    app.dependency_overrides[get_db] = _get_test_db
    app.dependency_overrides[get_tenant_db] = _get_test_db
    try:
        yield TestClient(app)
    finally:
        for dep in (get_current_user, get_db, get_tenant_db):
            app.dependency_overrides.pop(dep, None)


@pytest.fixture()
def as_org(db_session):
    """Factory: return a TestClient acting as ``org_id``.

    Both auth and the tenant DB dependency are overridden onto the shared,
    restricted ``db_session`` bound to the requested org, so endpoint tests run
    under real RLS. Calling the factory again re-binds to a different org within
    the same test transaction, which is how cross-org isolation is exercised.
    """
    from fastapi.testclient import TestClient

    from app.core.auth import CurrentUser, get_current_user
    from app.core.tenancy import bind_session_to_org, get_tenant_db
    from app.main import app

    def _act_as(org_id: str) -> TestClient:
        app.dependency_overrides[get_current_user] = lambda: CurrentUser(
            user_id="test-user", org_id=org_id
        )

        def _tenant_db():
            bind_session_to_org(db_session, org_id)
            yield db_session

        app.dependency_overrides[get_tenant_db] = _tenant_db
        return TestClient(app)

    yield _act_as
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_tenant_db, None)
