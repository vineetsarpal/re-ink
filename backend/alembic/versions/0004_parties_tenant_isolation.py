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


def upgrade() -> None:
    op.add_column("parties", sa.Column("org_id", sa.String(length=255), nullable=True))
    op.execute(f"UPDATE parties SET org_id = '{LEGACY_ORG_ID}' WHERE org_id IS NULL")
    op.alter_column("parties", "org_id", nullable=False)
    op.execute(
        "ALTER TABLE parties ALTER COLUMN org_id "
        "SET DEFAULT current_setting('app.current_org', true)"
    )

    # Registration numbers are unique per organization, not platform-wide.
    op.drop_constraint("parties_registration_number_key", "parties", type_="unique")
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
