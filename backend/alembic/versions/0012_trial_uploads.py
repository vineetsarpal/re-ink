"""Record provider notices and fence uploads before private storage writes."""
from alembic import op
import sqlalchemy as sa

revision = "0012_trial_uploads"
down_revision = "0011_maintenance"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "provider_acknowledgments",
        sa.Column("org_id", sa.String(255), primary_key=True),
        sa.Column("provider", sa.String(32), primary_key=True),
        sa.Column("notice_version", sa.String(64), nullable=False),
        sa.Column("acknowledged_by", sa.String(255), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "upload_intents",
        sa.Column("job_id", sa.String(100), primary_key=True),
        sa.Column("org_id", sa.String(255), nullable=False),
        sa.Column("storage_key", sa.String(500), nullable=False, unique=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("lease_deadline", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('uploading', 'completed', 'abandoned')"),
    )
    for table in ("provider_acknowledgments", "upload_intents"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY {table}_org_isolation ON {table} USING (org_id = current_setting('app.current_org', true)) WITH CHECK (org_id = current_setting('app.current_org', true))")
    op.execute(r"""
      CREATE OR REPLACE FUNCTION public.reink_storage_key_referenced(p_key text)
      RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
      BEGIN
        IF p_key IS NULL OR p_key !~ '^originals/[0-9a-f]{64}/[0-9a-f-]{36}/original[.](pdf|docx)$' THEN
          RAISE EXCEPTION 'Invalid object key';
        END IF;
        RETURN EXISTS (SELECT 1 FROM public.extraction_jobs j WHERE j.storage_key = p_key)
            OR EXISTS (SELECT 1 FROM public.storage_cleanup c WHERE c.storage_key = p_key)
            OR EXISTS (SELECT 1 FROM public.upload_intents i WHERE i.storage_key = p_key AND i.status = 'uploading');
      END;
      $$
    """)


def downgrade():
    op.execute(r"""
      CREATE OR REPLACE FUNCTION public.reink_storage_key_referenced(p_key text)
      RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
      BEGIN
        IF p_key IS NULL OR p_key !~ '^originals/[0-9a-f]{64}/[0-9a-f-]{36}/original[.](pdf|docx)$' THEN
          RAISE EXCEPTION 'Invalid object key';
        END IF;
        RETURN EXISTS (SELECT 1 FROM public.extraction_jobs j WHERE j.storage_key = p_key)
            OR EXISTS (SELECT 1 FROM public.storage_cleanup c WHERE c.storage_key = p_key);
      END;
      $$
    """)
    op.drop_table("upload_intents")
    op.drop_table("provider_acknowledgments")
