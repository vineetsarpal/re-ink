"""Retain expired upload tombstones and rescan for late storage writes."""
from alembic import op
import sqlalchemy as sa

revision = "0014_upload_reconciliation"
down_revision = "0013_cleanup_safety"
branch_labels = depends_on = None


def upgrade():
    op.add_column('upload_intents', sa.Column('next_cleanup_at', sa.DateTime(timezone=True)))
    op.add_column('upload_intents', sa.Column('cleanup_token', sa.String(64)))
    op.add_column('upload_intents', sa.Column('cleanup_lease_until', sa.DateTime(timezone=True)))
    op.execute('CREATE TABLE public.cleanup_turn (id boolean PRIMARY KEY DEFAULT true CHECK (id), upload_first boolean NOT NULL)')
    op.execute('INSERT INTO public.cleanup_turn (id, upload_first) VALUES (true, false)')
    op.execute('REVOKE ALL ON public.cleanup_turn FROM PUBLIC')
    op.execute('''
      CREATE FUNCTION public.reink_cleanup_upload_first() RETURNS boolean
      LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
      DECLARE result boolean;
      BEGIN
        UPDATE public.cleanup_turn SET upload_first = NOT upload_first WHERE id = true
          RETURNING upload_first INTO result;
        RETURN result;
      END $$;
      CREATE FUNCTION public.reink_lease_expired_upload(p_token varchar)
      RETURNS TABLE(job_id varchar, org_id varchar, storage_key varchar)
      LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
      DECLARE item public.upload_intents%ROWTYPE;
      BEGIN
        SELECT i.* INTO item FROM public.upload_intents i
        WHERE ((i.status = 'uploading' AND i.lease_deadline <= pg_catalog.clock_timestamp())
            OR (i.status = 'abandoned' AND (i.next_cleanup_at IS NULL OR i.next_cleanup_at <= pg_catalog.clock_timestamp())))
          AND (i.cleanup_lease_until IS NULL OR i.cleanup_lease_until <= pg_catalog.clock_timestamp())
          AND NOT EXISTS (SELECT 1 FROM public.extraction_jobs j WHERE j.storage_key = i.storage_key)
          AND NOT EXISTS (SELECT 1 FROM public.storage_cleanup c WHERE c.storage_key = i.storage_key)
        ORDER BY COALESCE(i.next_cleanup_at, i.lease_deadline), i.job_id
        FOR UPDATE OF i SKIP LOCKED LIMIT 1;
        IF NOT FOUND THEN RETURN; END IF;
        UPDATE public.upload_intents i SET status = 'abandoned', cleanup_token = p_token,
          cleanup_lease_until = pg_catalog.clock_timestamp() + interval '2 minutes'
          WHERE i.job_id = item.job_id;
        RETURN QUERY SELECT item.job_id, item.org_id, item.storage_key;
      END $$;
      CREATE FUNCTION public.reink_expired_upload_is_safe(p_job varchar, p_token varchar) RETURNS boolean
      LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
      DECLARE item public.upload_intents%ROWTYPE;
      BEGIN
        SELECT i.* INTO item FROM public.upload_intents i WHERE i.job_id = p_job
          AND i.status = 'abandoned' AND i.cleanup_token = p_token
          AND i.cleanup_lease_until > pg_catalog.clock_timestamp() FOR UPDATE;
        IF NOT FOUND THEN RETURN false; END IF;
        RETURN NOT EXISTS (SELECT 1 FROM public.extraction_jobs j WHERE j.storage_key = item.storage_key)
           AND NOT EXISTS (SELECT 1 FROM public.storage_cleanup c WHERE c.storage_key = item.storage_key);
      END $$;
      CREATE FUNCTION public.reink_finish_expired_upload(p_job varchar, p_token varchar, p_success boolean) RETURNS boolean
      LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
      BEGIN
        UPDATE public.upload_intents i SET cleanup_token = NULL, cleanup_lease_until = NULL,
          next_cleanup_at = pg_catalog.clock_timestamp() + CASE WHEN p_success THEN interval '24 hours' ELSE interval '5 minutes' END
        WHERE i.job_id = p_job AND i.status = 'abandoned' AND i.cleanup_token = p_token
          AND i.cleanup_lease_until > pg_catalog.clock_timestamp();
        RETURN FOUND;
      END $$;
    ''')
    for name in ('reink_cleanup_upload_first()', 'reink_lease_expired_upload(varchar)',
                 'reink_expired_upload_is_safe(varchar, varchar)', 'reink_finish_expired_upload(varchar, varchar, boolean)'):
        op.execute(f'REVOKE ALL ON FUNCTION public.{name} FROM PUBLIC')


def downgrade():
    for name in ('reink_finish_expired_upload(varchar, varchar, boolean)', 'reink_expired_upload_is_safe(varchar, varchar)',
                 'reink_lease_expired_upload(varchar)', 'reink_cleanup_upload_first()'):
        op.execute(f'DROP FUNCTION public.{name}')
    op.execute('DROP TABLE public.cleanup_turn')
    op.drop_column('upload_intents', 'cleanup_lease_until')
    op.drop_column('upload_intents', 'cleanup_token')
    op.drop_column('upload_intents', 'next_cleanup_at')
