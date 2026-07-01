"""extraction_jobs tenant isolation: org_id + RLS

Revision ID: 0005_extraction_jobs_isolation
Revises: 0004_parties_tenant_isolation
Create Date: 2026-06-30

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0005_extraction_jobs_isolation"
down_revision: Union[str, None] = "0004_parties_tenant_isolation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LEGACY_ORG_ID = "org_01KV720766F2G63DEE1XR5FKJ0"


def upgrade() -> None:
    op.add_column(
        "extraction_jobs", sa.Column("org_id", sa.String(length=255), nullable=True)
    )
    op.execute(
        f"UPDATE extraction_jobs SET org_id = '{LEGACY_ORG_ID}' WHERE org_id IS NULL"
    )
    op.alter_column("extraction_jobs", "org_id", nullable=False)
    op.execute(
        "ALTER TABLE extraction_jobs ALTER COLUMN org_id "
        "SET DEFAULT current_setting('app.current_org', true)"
    )

    op.execute("ALTER TABLE extraction_jobs ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY extraction_jobs_org_isolation ON extraction_jobs "
        "USING (org_id = current_setting('app.current_org', true)) "
        "WITH CHECK (org_id = current_setting('app.current_org', true))"
    )


def downgrade() -> None:
    op.execute(
        "DROP POLICY IF EXISTS extraction_jobs_org_isolation ON extraction_jobs"
    )
    op.execute("ALTER TABLE extraction_jobs DISABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE extraction_jobs ALTER COLUMN org_id DROP DEFAULT")
    op.drop_column("extraction_jobs", "org_id")
