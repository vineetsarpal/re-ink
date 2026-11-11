"""Add durable per-organization trial usage and attempt reservations."""
from alembic import op
import sqlalchemy as sa

revision = "0009_trial_quotas"
down_revision = "0008_provider_credentials"
branch_labels = depends_on = None


def upgrade():
    op.create_table("extraction_quota_global",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("month", sa.Date, nullable=False),
        sa.Column("trial_successes", sa.Integer, nullable=False),
        sa.Column("trial_pending", sa.Integer, nullable=False),
        sa.Column("trial_starts", sa.Integer, nullable=False, server_default="0"),
        sa.CheckConstraint("id = 1 AND trial_successes >= 0 AND trial_pending >= 0 AND trial_starts >= 0"))
    op.create_table("extraction_quota_org",
        sa.Column("org_id", sa.String(255), primary_key=True),
        sa.Column("month", sa.Date, nullable=False),
        sa.Column("monthly_successes", sa.Integer, nullable=False),
        sa.Column("monthly_attempts", sa.Integer, nullable=False),
        sa.Column("pending", sa.Integer, nullable=False),
        sa.Column("free_successes", sa.Integer, nullable=False),
        sa.Column("free_pending", sa.Integer, nullable=False),
        sa.CheckConstraint("monthly_successes >= 0 AND monthly_attempts >= 0 AND pending >= 0 AND free_successes >= 0 AND free_pending >= 0"))
    op.create_table("extraction_quota_reservations",
        sa.Column("org_id", sa.String(255), primary_key=True),
        sa.Column("attempt_id", sa.String(128), primary_key=True),
        sa.Column("funding", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("credential_snapshot", sa.LargeBinary),
        sa.Column("provider_started", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.CheckConstraint("funding IN ('trial', 'customer')"),
        sa.CheckConstraint("status IN ('pending', 'succeeded', 'failed')"))
    op.create_table("extraction_rate_org",
        sa.Column("org_id", sa.String(255), primary_key=True),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer, nullable=False),
        sa.CheckConstraint("attempts >= 0"))
    for table in ("extraction_quota_org", "extraction_quota_reservations", "extraction_rate_org"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY {table}_isolation ON {table} USING (org_id = current_setting('app.current_org', true)) WITH CHECK (org_id = current_setting('app.current_org', true))")


def downgrade():
    op.drop_table("extraction_rate_org")
    op.drop_table("extraction_quota_reservations")
    op.drop_table("extraction_quota_org")
    op.drop_table("extraction_quota_global")
