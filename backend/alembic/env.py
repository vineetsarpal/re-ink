"""
Alembic environment configuration.

The database URL and engine are imported directly from the application's
own database module (app.db.database) so Alembic and the app always agree
on the driver, SSL settings, and connection parameters.  The URL is never
read from alembic.ini.
"""
import sys
import os
from logging.config import fileConfig

from sqlalchemy import pool
from alembic import context

# ---------------------------------------------------------------------------
# Make the ``app`` package importable when alembic is invoked from backend/.
# alembic.ini sets prepend_sys_path = . which adds backend/ to sys.path, but
# we also do it here defensively so ``alembic`` commands run from any cwd work.
# ---------------------------------------------------------------------------
_backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

# ---------------------------------------------------------------------------
# Import the already-built engine and Base from the app so we share the exact
# same connection configuration (driver rewrite, pool settings, etc.).
# Importing app.models ensures all ORM classes are registered on Base.metadata
# before we pass it to Alembic.
# ---------------------------------------------------------------------------
from app.db.database import engine, Base  # noqa: E402
import app.models  # noqa: F401 — registers Party, Contract, contract_parties, ExtractionJob

# ---------------------------------------------------------------------------
# Alembic Config object — gives access to alembic.ini values.
# ---------------------------------------------------------------------------
config = context.config

# Interpret the logging config in alembic.ini.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Full metadata so Alembic can diff the schema.
target_metadata = Base.metadata


# ---------------------------------------------------------------------------
# Migration runners
# ---------------------------------------------------------------------------

def run_migrations_offline() -> None:
    """
    Run migrations in 'offline' mode.

    In this mode SQLAlchemy does not need a live DB connection — it emits
    SQL to stdout (or a file) using literal parameter rendering.  This is
    what ``alembic upgrade head --sql`` uses.
    """
    url = str(engine.url)
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    Run migrations in 'online' mode using the app's engine directly.

    We pass the engine (not a connection string) so that the pool and SSL
    settings configured in app.db.database are reused verbatim.
    """
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
