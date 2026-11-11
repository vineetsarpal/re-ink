"""Back off consecutive upload tombstone deletion failures, capped at one day."""
from alembic import op
import sqlalchemy as sa

revision = "0016_cleanup_backoff"
down_revision = "0015_trial_hardening"
branch_labels = depends_on = None

FINISH = """
CREATE OR REPLACE FUNCTION public.reink_finish_expired_upload(p_job varchar, p_token varchar, p_success boolean) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
BEGIN
  UPDATE public.upload_intents i SET cleanup_token = NULL, cleanup_lease_until = NULL,
    status = CASE WHEN p_success AND i.lease_deadline <= pg_catalog.clock_timestamp() - interval '7 days'
      THEN 'deleted' ELSE i.status END,
    {failures}
    next_cleanup_at = pg_catalog.clock_timestamp() + CASE WHEN p_success THEN interval '24 hours'
      ELSE {delay} END
  WHERE i.job_id = p_job AND i.status = 'abandoned' AND i.cleanup_token = p_token
    AND i.cleanup_lease_until > pg_catalog.clock_timestamp();
  RETURN FOUND;
END $$
"""


# Frozen SQL from 0015 upgrade, including its exact function body.
PREVIOUS_FINISH = """
  CREATE OR REPLACE FUNCTION public.reink_finish_expired_upload(p_job varchar, p_token varchar, p_success boolean) RETURNS boolean
  LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
  BEGIN
    UPDATE public.upload_intents i SET cleanup_token = NULL, cleanup_lease_until = NULL,
      status = CASE WHEN p_success AND i.lease_deadline <= pg_catalog.clock_timestamp() - interval '7 days' THEN 'deleted' ELSE i.status END,
      next_cleanup_at = pg_catalog.clock_timestamp() + CASE WHEN p_success THEN interval '24 hours' ELSE interval '5 minutes' END
    WHERE i.job_id = p_job AND i.status = 'abandoned' AND i.cleanup_token = p_token
      AND i.cleanup_lease_until > pg_catalog.clock_timestamp();
    RETURN FOUND;
  END $$
"""

def upgrade():
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.add_column('upload_intents', sa.Column('cleanup_failures', sa.Integer(), nullable=False, server_default='0'))
    op.execute(FINISH.format(
        failures="cleanup_failures = CASE WHEN p_success THEN 0 ELSE LEAST(i.cleanup_failures, 9) + 1 END,",
        delay="LEAST(interval '24 hours', interval '5 minutes' * power(2, LEAST(i.cleanup_failures, 9)))",
    ))


def downgrade():
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(PREVIOUS_FINISH)
    op.drop_column('upload_intents', 'cleanup_failures')
