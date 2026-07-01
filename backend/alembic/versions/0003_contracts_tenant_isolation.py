"""contracts tenant isolation: org_id + RLS

Revision ID: 0003_contracts_tenant_isolation
Revises: 0002_drop_redundant_pk_indexes
Create Date: 2026-06-30

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003_contracts_tenant_isolation"
down_revision: Union[str, None] = "0002_drop_redundant_pk_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Legacy (demo) rows are attributed to the operator's WorkOS "Test Organization".
LEGACY_ORG_ID = "org_01KV720766F2G63DEE1XR5FKJ0"


def upgrade() -> None:
    op.add_column("contracts", sa.Column("org_id", sa.String(length=255), nullable=True))
    op.execute(
        f"UPDATE contracts SET org_id = '{LEGACY_ORG_ID}' WHERE org_id IS NULL"
    )
    op.alter_column("contracts", "org_id", nullable=False)
    # New rows are stamped from the GUC, so app code never has to set org_id.
    op.execute(
        "ALTER TABLE contracts ALTER COLUMN org_id "
        "SET DEFAULT current_setting('app.current_org', true)"
    )

    # Contract numbers are unique per organization, not platform-wide.
    op.drop_constraint("contracts_contract_number_key", "contracts", type_="unique")
    op.create_unique_constraint(
        "uq_contracts_org_contract_number", "contracts", ["org_id", "contract_number"]
    )

    op.execute("ALTER TABLE contracts ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY contracts_org_isolation ON contracts "
        "USING (org_id = current_setting('app.current_org', true)) "
        "WITH CHECK (org_id = current_setting('app.current_org', true))"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS contracts_org_isolation ON contracts")
    op.execute("ALTER TABLE contracts DISABLE ROW LEVEL SECURITY")
    op.drop_constraint("uq_contracts_org_contract_number", "contracts", type_="unique")
    op.create_unique_constraint(
        "contracts_contract_number_key", "contracts", ["contract_number"]
    )
    op.execute("ALTER TABLE contracts ALTER COLUMN org_id DROP DEFAULT")
    op.drop_column("contracts", "org_id")
