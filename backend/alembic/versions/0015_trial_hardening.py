"""Index reconciliation lookups, retire upload tombstones, harden definer functions."""
from alembic import op

revision = "0015_trial_hardening"
down_revision = "0014_upload_reconciliation"
branch_labels = depends_on = None

APP_ROLE = "reink_app"
# A PUT is a single 30s-timeout request inside a 15-minute lease; a week of
# daily rescans after the lease far exceeds any plausible delayed write.
TOMBSTONE_WINDOW = "7 days"

FINISH = """
  CREATE OR REPLACE FUNCTION public.reink_finish_expired_upload(p_job varchar, p_token varchar, p_success boolean) RETURNS boolean
  LANGUAGE plpgsql SECURITY DEFINER SET search_path = {path} AS $$
  BEGIN
    UPDATE public.upload_intents i SET cleanup_token = NULL, cleanup_lease_until = NULL,
      {retire}next_cleanup_at = pg_catalog.clock_timestamp() + CASE WHEN p_success THEN interval '24 hours' ELSE interval '5 minutes' END
    WHERE i.job_id = p_job AND i.status = 'abandoned' AND i.cleanup_token = p_token
      AND i.cleanup_lease_until > pg_catalog.clock_timestamp();
    RETURN FOUND;
  END $$
"""
RETIRE = (f"status = CASE WHEN p_success AND i.lease_deadline <= pg_catalog.clock_timestamp() - interval '{TOMBSTONE_WINDOW}' "
          "THEN 'deleted' ELSE i.status END,\n      ")

DEFINER_FUNCTIONS = """
  SELECT p.oid::regprocedure AS fn FROM pg_catalog.pg_proc p
  JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace
  WHERE n.nspname = 'public' AND p.prosecdef AND p.proname LIKE 'reink\\_%'
"""


def revoke_app_execute_sql(role=APP_ROLE):
    # Owner default privileges (e.g. on Neon) may have granted the app role EXECUTE.
    return f"""
      DO $$
      DECLARE f regprocedure;
      BEGIN
        IF EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = '{role}') THEN
          FOR f IN {DEFINER_FUNCTIONS} LOOP
            EXECUTE pg_catalog.format('REVOKE ALL ON FUNCTION %s FROM %I', f, '{role}');
          END LOOP;
          EXECUTE pg_catalog.format('REVOKE ALL ON public.cleanup_turn FROM %I', '{role}');
          -- REVOKE cannot remove grants from other grantors or inherited memberships.
          FOR f IN {DEFINER_FUNCTIONS} LOOP
            IF pg_catalog.has_function_privilege('{role}', f, 'EXECUTE') THEN
              RAISE EXCEPTION '% still has access to %', '{role}', f;
            END IF;
          END LOOP;
          IF pg_catalog.has_table_privilege('{role}', 'public.cleanup_turn', 'SELECT,INSERT,UPDATE,DELETE') THEN
            RAISE EXCEPTION '% still has access to public.cleanup_turn', '{role}';
          END IF;
        END IF;
      END $$
    """


def _set_search_path(path):
    op.execute(f"""
      DO $$
      DECLARE f regprocedure;
      BEGIN
        FOR f IN {DEFINER_FUNCTIONS} LOOP
          EXECUTE pg_catalog.format('ALTER FUNCTION %s SET search_path = {path}', f);
        END LOOP;
      END $$
    """)


def _status_check(values):
    op.execute("""
      DO $$
      DECLARE c name;
      BEGIN
        FOR c IN SELECT conname FROM pg_catalog.pg_constraint
          WHERE conrelid = 'public.upload_intents'::regclass AND contype = 'c'
            AND pg_catalog.pg_get_constraintdef(oid) LIKE '%status%' LOOP
          EXECUTE pg_catalog.format('ALTER TABLE public.upload_intents DROP CONSTRAINT %I', c);
        END LOOP;
      END $$
    """)
    listed = ", ".join(f"'{v}'" for v in values)
    op.execute(f"ALTER TABLE public.upload_intents ADD CONSTRAINT upload_intents_status_check CHECK (status IN ({listed}))")


def upgrade():
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("CREATE INDEX IF NOT EXISTS ix_extraction_jobs_storage_key ON public.extraction_jobs (storage_key)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_storage_cleanup_storage_key ON public.storage_cleanup (storage_key)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_upload_intents_reconcile ON public.upload_intents "
               "(COALESCE(next_cleanup_at, lease_deadline), job_id) WHERE status IN ('uploading', 'abandoned')")
    _status_check(("uploading", "completed", "abandoned", "deleted"))
    op.execute(FINISH.format(path="pg_catalog, pg_temp", retire=RETIRE))
    _set_search_path("pg_catalog, pg_temp")
    op.execute("REVOKE ALL ON FUNCTION public.reink_finish_expired_upload(varchar, varchar, boolean) FROM PUBLIC")
    op.execute(revoke_app_execute_sql())


def downgrade():
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(FINISH.format(path="pg_catalog", retire=""))
    _set_search_path("pg_catalog")
    op.execute("UPDATE public.upload_intents SET status = 'abandoned', "
               "next_cleanup_at = COALESCE(next_cleanup_at, pg_catalog.clock_timestamp()) WHERE status = 'deleted'")
    _status_check(("uploading", "completed", "abandoned"))
    op.execute("DROP INDEX IF EXISTS public.ix_upload_intents_reconcile")
    op.execute("DROP INDEX IF EXISTS public.ix_storage_cleanup_storage_key")
    op.execute("DROP INDEX IF EXISTS public.ix_extraction_jobs_storage_key")
