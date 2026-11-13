"""Preserve full extracted financial descriptions without truncation."""
from alembic import op
import sqlalchemy as sa

revision = "0022_financial_descriptions"
down_revision = "0021_purge_role"
branch_labels = depends_on = None

FIELDS = (
    "premium_description", "limit_description",
    "retention_description", "commission_description",
)


def upgrade():
    for field in FIELDS:
        op.alter_column("contracts", field, existing_type=sa.String(255), type_=sa.Text())


def downgrade():
    # PostgreSQL refuses this downgrade if long descriptions exist, preserving
    # their contents instead of silently truncating financial terms.
    for field in FIELDS:
        op.alter_column("contracts", field, existing_type=sa.Text(), type_=sa.String(255))
