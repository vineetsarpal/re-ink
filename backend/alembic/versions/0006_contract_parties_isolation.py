"""contract_parties tenant isolation: org_id + RLS

Revision ID: 0006_contract_parties_isolation
Revises: 0005_extraction_jobs_isolation
Create Date: 2026-07-01

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0006_contract_parties_isolation"
down_revision: Union[str, None] = "0005_extraction_jobs_isolation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "contract_parties", sa.Column("org_id", sa.String(length=255), nullable=True)
    )
    # Each association belongs to the same org as its contract.
    op.execute(
        "UPDATE contract_parties cp SET org_id = c.org_id "
        "FROM contracts c WHERE cp.contract_id = c.id AND cp.org_id IS NULL"
    )
    op.alter_column("contract_parties", "org_id", nullable=False)
    op.execute(
        "ALTER TABLE contract_parties ALTER COLUMN org_id "
        "SET DEFAULT current_setting('app.current_org', true)"
    )

    op.execute("ALTER TABLE contract_parties ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY contract_parties_org_isolation ON contract_parties "
        "USING (org_id = current_setting('app.current_org', true)) "
        "WITH CHECK (org_id = current_setting('app.current_org', true))"
    )


def downgrade() -> None:
    op.execute(
        "DROP POLICY IF EXISTS contract_parties_org_isolation ON contract_parties"
    )
    op.execute("ALTER TABLE contract_parties DISABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE contract_parties ALTER COLUMN org_id DROP DEFAULT")
    op.drop_column("contract_parties", "org_id")
