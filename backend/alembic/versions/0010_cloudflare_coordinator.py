"""Store a durable, one-shot provider-call fence and terminal checkpoint."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0010_cloudflare_coordinator"
down_revision = "0009_trial_quotas"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "cloudflare_executions",
        sa.Column("attempt_id", sa.String(128), sa.ForeignKey("extraction_attempts.attempt_id", ondelete="CASCADE"), primary_key=True),
        sa.Column("org_id", sa.String(255), nullable=False),
        sa.Column("token_digest", sa.String(64), nullable=False),
        sa.Column("terminal_event", JSONB(), nullable=True),
    )
    op.execute("ALTER TABLE cloudflare_executions ENABLE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY cloudflare_executions_org_isolation ON cloudflare_executions USING (org_id = current_setting('app.current_org', true)) WITH CHECK (org_id = current_setting('app.current_org', true))")


def downgrade():
    op.drop_table("cloudflare_executions")
