"""Drop redundant indexes on primary-key columns.

PostgreSQL automatically creates a unique index on every primary key, so the
explicit indexes on ``parties.id``, ``contracts.id``, and
``extraction_jobs.job_id`` created in the baseline migration are redundant.
This migration removes them.

Revision ID: 0002_drop_redundant_pk_indexes
Revises: 0001_baseline
Create Date: 2026-06-14
"""
from typing import Sequence, Union

from alembic import op

# ---------------------------------------------------------------------------
# Revision identifiers
# ---------------------------------------------------------------------------
revision: str = "0002_drop_redundant_pk_indexes"
down_revision: Union[str, None] = "0001_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ---------------------------------------------------------------------------
# upgrade — drop the three redundant PK indexes
# ---------------------------------------------------------------------------

def upgrade() -> None:
    op.drop_index(op.f("ix_parties_id"), table_name="parties")
    op.drop_index(op.f("ix_contracts_id"), table_name="contracts")
    op.drop_index(op.f("ix_extraction_jobs_job_id"), table_name="extraction_jobs")


# ---------------------------------------------------------------------------
# downgrade — recreate the indexes so the baseline state is restored
# ---------------------------------------------------------------------------

def downgrade() -> None:
    op.create_index(op.f("ix_extraction_jobs_job_id"), "extraction_jobs", ["job_id"], unique=False)
    op.create_index(op.f("ix_contracts_id"), "contracts", ["id"], unique=False)
    op.create_index(op.f("ix_parties_id"), "parties", ["id"], unique=False)
