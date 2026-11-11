"""Add restricted discovery functions for extraction maintenance."""
from alembic import op

revision = "0011_maintenance"
down_revision = "0010_cloudflare_coordinator"
branch_labels = depends_on = None


def upgrade():
    # Owned by the migration/table owner. No dynamic SQL, caller arguments,
    # document data or credentials are exposed. The owner-only provisioning
    # script grants EXECUTE to a dedicated maintenance role explicitly.
    op.execute("""
        CREATE FUNCTION public.reink_next_expired_extraction()
        RETURNS TABLE (org_id varchar, job_id varchar)
        LANGUAGE sql SECURITY DEFINER
        SET search_path = pg_catalog
        AS $$
          SELECT j.org_id, j.job_id
          FROM public.extraction_jobs AS j
          JOIN public.extraction_attempts AS a ON a.attempt_id = j.selected_attempt_id
          WHERE j.deleted_at IS NULL
            AND a.status IN ('queued', 'processing')
            AND a.deadline_at <= pg_catalog.clock_timestamp()
          ORDER BY a.deadline_at, j.job_id
          LIMIT 1
        $$
    """)
    op.execute("REVOKE ALL ON FUNCTION public.reink_next_expired_extraction() FROM PUBLIC")
    op.execute("""
        CREATE FUNCTION public.reink_next_due_dispatch_org()
        RETURNS varchar LANGUAGE sql SECURITY DEFINER
        SET search_path = pg_catalog AS $$
          SELECT o.org_id
          FROM public.workflow_outbox AS o
          JOIN public.extraction_attempts AS a ON a.attempt_id = o.attempt_id
          JOIN public.extraction_jobs AS j ON j.job_id = a.job_id
          WHERE o.acknowledged_at IS NULL
            AND o.next_delivery_at <= pg_catalog.clock_timestamp()
            AND (o.lease_until IS NULL OR o.lease_until <= pg_catalog.clock_timestamp())
            AND a.status IN ('queued', 'processing')
            AND a.deadline_at > pg_catalog.clock_timestamp()
            AND j.deleted_at IS NULL AND j.selected_attempt_id = o.attempt_id
          ORDER BY o.next_delivery_at, o.attempt_id
          LIMIT 1
        $$
    """)
    op.execute("REVOKE ALL ON FUNCTION public.reink_next_due_dispatch_org() FROM PUBLIC")
    op.execute("""
        CREATE FUNCTION public.reink_next_cleanup_org() RETURNS varchar
        LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog AS $$
          SELECT c.org_id FROM public.storage_cleanup AS c
          WHERE c.completed_at IS NULL AND c.next_attempt_at <= pg_catalog.clock_timestamp()
            AND (c.lease_until IS NULL OR c.lease_until <= pg_catalog.clock_timestamp())
          ORDER BY c.next_attempt_at, c.cleanup_id LIMIT 1
        $$
    """)
    op.execute("""
        CREATE FUNCTION public.reink_finish_storage_cleanup(p_id varchar, p_token varchar)
        RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE item public.storage_cleanup%ROWTYPE;
        BEGIN
          SELECT * INTO item FROM public.storage_cleanup c
          WHERE c.cleanup_id = p_id AND c.org_id = pg_catalog.current_setting('app.current_org', true)
            AND c.lease_token = p_token AND c.lease_until > pg_catalog.clock_timestamp()
            AND c.completed_at IS NULL FOR UPDATE;
          IF NOT FOUND THEN RETURN false; END IF;
          IF item.job_id IS NOT NULL AND EXISTS (
            SELECT 1 FROM public.extraction_jobs j
            WHERE j.job_id = item.job_id AND j.org_id = item.org_id AND j.deleted_at IS NULL
          ) THEN RETURN false; END IF;
          DELETE FROM public.extraction_jobs j
          WHERE j.job_id = item.job_id AND j.org_id = item.org_id AND j.deleted_at IS NOT NULL;
          DELETE FROM public.storage_cleanup c WHERE c.cleanup_id = item.cleanup_id AND c.org_id = item.org_id;
          RETURN true;
        END;
        $$
    """)
    op.execute("REVOKE ALL ON FUNCTION public.reink_next_cleanup_org() FROM PUBLIC")
    op.execute("REVOKE ALL ON FUNCTION public.reink_finish_storage_cleanup(varchar, varchar) FROM PUBLIC")
    op.execute(r"""
        CREATE FUNCTION public.reink_storage_key_referenced(p_key text)
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
    op.execute("REVOKE ALL ON FUNCTION public.reink_storage_key_referenced(text) FROM PUBLIC")


def downgrade():
    op.execute("DROP FUNCTION public.reink_storage_key_referenced(text)")
    op.execute("DROP FUNCTION public.reink_finish_storage_cleanup(varchar, varchar)")
    op.execute("DROP FUNCTION public.reink_next_cleanup_org()")
    op.execute("DROP FUNCTION public.reink_next_due_dispatch_org()")
    op.execute("DROP FUNCTION public.reink_next_expired_extraction()")
