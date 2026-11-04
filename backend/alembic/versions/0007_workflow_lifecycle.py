"""Add workflow lifecycle tables; legacy jobs remain excluded from dispatch."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
revision = "0007_workflow_lifecycle"
down_revision = "0006_contract_parties_isolation"
branch_labels = depends_on = None


def upgrade():
    for name, kind in [("selected_attempt_id", sa.String(128)), ("storage_key", sa.String(500)), ("content_type", sa.String(150)), ("size_bytes", sa.BigInteger()), ("sha256", sa.String(64)), ("deleted_at", sa.DateTime(timezone=True))]:
        op.add_column("extraction_jobs", sa.Column(name, kind))
    op.create_table("extraction_attempts", sa.Column("attempt_id", sa.String(128), primary_key=True), sa.Column("job_id", sa.String(100), sa.ForeignKey("extraction_jobs.job_id"), nullable=False), sa.Column("org_id", sa.String(255), nullable=False), sa.Column("number", sa.Integer(), nullable=False), sa.Column("status", sa.String(20), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=False), sa.Column("accepted_at", sa.DateTime(timezone=True)), sa.Column("completed_at", sa.DateTime(timezone=True)), sa.Column("execution_key", sa.String(128)), sa.Column("workflow_execution_id", sa.String(128)), sa.Column("error_code", sa.String(100)), sa.Column("error_message", sa.Text()), sa.UniqueConstraint("job_id", "number"))
    op.create_table("workflow_outbox", sa.Column("attempt_id", sa.String(128), sa.ForeignKey("extraction_attempts.attempt_id"), primary_key=True), sa.Column("org_id", sa.String(255), nullable=False), sa.Column("payload", JSONB, nullable=False), sa.Column("next_delivery_at", sa.DateTime(timezone=True), nullable=False), sa.Column("lease_token", sa.String(128)), sa.Column("lease_until", sa.DateTime(timezone=True)), sa.Column("delivery_count", sa.Integer(), nullable=False), sa.Column("acknowledged_at", sa.DateTime(timezone=True)), sa.Column("last_error", sa.String(100)))
    op.create_index("workflow_outbox_due", "workflow_outbox", ["next_delivery_at", "lease_until"])
    op.create_table("workflow_receipts", sa.Column("attempt_id", sa.String(128), sa.ForeignKey("extraction_attempts.attempt_id"), primary_key=True), sa.Column("event_id", sa.String(128), primary_key=True), sa.Column("org_id", sa.String(255), nullable=False), sa.Column("digest", sa.String(64), nullable=False), sa.Column("acknowledgement", JSONB, nullable=False))
    op.create_table("storage_cleanup", sa.Column("cleanup_id", sa.String(128), primary_key=True), sa.Column("org_id", sa.String(255), nullable=False), sa.Column("storage_key", sa.String(500), nullable=False), sa.Column("job_id", sa.String(100)), sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False), sa.Column("attempts", sa.Integer(), nullable=False), sa.Column("completed_at", sa.DateTime(timezone=True)), sa.Column("lease_token", sa.String(128)), sa.Column("lease_until", sa.DateTime(timezone=True)))
    for table in ("extraction_attempts", "workflow_outbox", "workflow_receipts", "storage_cleanup"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY {table}_org_isolation ON {table} USING (org_id = current_setting('app.current_org', true)) WITH CHECK (org_id = current_setting('app.current_org', true))")


def downgrade():
    for table in ("storage_cleanup", "workflow_receipts", "workflow_outbox", "extraction_attempts"):
        op.drop_table(table)
    for name in ("deleted_at", "sha256", "size_bytes", "content_type", "storage_key", "selected_attempt_id"):
        op.drop_column("extraction_jobs", name)
