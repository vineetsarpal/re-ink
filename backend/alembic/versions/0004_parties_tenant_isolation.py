"""parties tenant isolation: org_id + RLS

Revision ID: 0004_parties_tenant_isolation
Revises: 0003_contracts_tenant_isolation
Create Date: 2026-06-30

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0004_parties_tenant_isolation"
down_revision: Union[str, None] = "0003_contracts_tenant_isolation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LEGACY_ORG_ID = "org_01KV720766F2G63DEE1XR5FKJ0"


def _drop_single_column_unique(table_name: str, column_name: str) -> None:
    """Drop legacy single-column uniqueness from either Alembic or create_all."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    for constraint in inspector.get_unique_constraints(table_name):
        if constraint.get("column_names") == [column_name] and constraint.get("name"):
            op.drop_constraint(constraint["name"], table_name, type_="unique")

    inspector = sa.inspect(bind)
    for index in inspector.get_indexes(table_name):
        if (
            index.get("unique")
            and index.get("column_names") == [column_name]
            and index.get("name")
        ):
            op.drop_index(index["name"], table_name=table_name)


def upgrade() -> None:
    op.add_column("parties", sa.Column("org_id", sa.String(length=255), nullable=True))
    op.execute(f"UPDATE parties SET org_id = '{LEGACY_ORG_ID}' WHERE org_id IS NULL")
    op.alter_column("parties", "org_id", nullable=False)
    op.execute(
        "ALTER TABLE parties ALTER COLUMN org_id "
        "SET DEFAULT current_setting('app.current_org', true)"
    )

    # Registration numbers are unique per organization, not platform-wide.
    _drop_single_column_unique("parties", "registration_number")
    op.create_unique_constraint(
        "uq_parties_org_registration_number", "parties", ["org_id", "registration_number"]
    )

    op.execute("ALTER TABLE parties ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY parties_org_isolation ON parties "
        "USING (org_id = current_setting('app.current_org', true)) "
        "WITH CHECK (org_id = current_setting('app.current_org', true))"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS parties_org_isolation ON parties")
    op.execute("ALTER TABLE parties DISABLE ROW LEVEL SECURITY")
    op.drop_constraint("uq_parties_org_registration_number", "parties", type_="unique")
    op.create_unique_constraint(
        "parties_registration_number_key", "parties", ["registration_number"]
    )
    op.execute("ALTER TABLE parties ALTER COLUMN org_id DROP DEFAULT")
    op.drop_column("parties", "org_id")
