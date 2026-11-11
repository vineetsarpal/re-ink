"""Store encrypted provider credentials under tenant row-level security."""
from alembic import op
import sqlalchemy as sa

revision = "0008_provider_credentials"
down_revision = "0007_workflow_lifecycle"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "provider_credentials",
        sa.Column("org_id", sa.String(255), primary_key=True),
        sa.Column("provider", sa.String(32), primary_key=True),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.execute("ALTER TABLE provider_credentials ENABLE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY provider_credentials_org_isolation ON provider_credentials USING (org_id = current_setting('app.current_org', true)) WITH CHECK (org_id = current_setting('app.current_org', true))")


def downgrade():
    op.drop_table("provider_credentials")
