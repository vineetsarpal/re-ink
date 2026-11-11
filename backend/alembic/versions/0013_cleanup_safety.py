"""Fence cleanup against a live job before deleting its original."""
from alembic import op

revision = "0013_cleanup_safety"
down_revision = "0012_trial_uploads"
branch_labels = depends_on = None


def upgrade():
    op.execute("""
      CREATE FUNCTION public.reink_cleanup_is_safe(p_id varchar, p_token varchar)
      RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
      DECLARE item public.storage_cleanup%ROWTYPE;
      BEGIN
        SELECT * INTO item FROM public.storage_cleanup c
        WHERE c.cleanup_id = p_id AND c.org_id = pg_catalog.current_setting('app.current_org', true)
          AND c.lease_token = p_token AND c.lease_until > pg_catalog.clock_timestamp()
          AND c.completed_at IS NULL FOR UPDATE;
        IF NOT FOUND OR item.job_id IS NULL THEN RETURN false; END IF;
        PERFORM 1 FROM public.extraction_jobs j
        WHERE j.job_id = item.job_id AND j.org_id = item.org_id AND j.deleted_at IS NOT NULL
          AND j.storage_key = item.storage_key
        FOR UPDATE;
        IF NOT FOUND THEN RETURN false; END IF;
        RETURN NOT EXISTS (SELECT 1 FROM public.extraction_jobs j
          WHERE j.storage_key = item.storage_key AND j.deleted_at IS NULL);
      END;
      $$
    """)
    op.execute("REVOKE ALL ON FUNCTION public.reink_cleanup_is_safe(varchar, varchar) FROM PUBLIC")


def downgrade():
    op.execute("DROP FUNCTION public.reink_cleanup_is_safe(varchar, varchar)")
