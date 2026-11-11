"""Expired upload cleanup through the authenticated scheduler endpoint."""
from pathlib import Path
import runpy
import sys
import time
from uuid import uuid4

import psycopg
from psycopg import sql
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.services.storage_service import tenant_prefix
from conftest import TEST_DATABASE_URL


def test_expired_upload_tombstone_cleans_late_put_and_preserves_live_original(monkeypatch):
    from app.api.endpoints import cleanup_maintenance

    role = 'reink_cleanup_' + uuid4().hex[:16]
    org = 'upload-cleanup-' + uuid4().hex
    jobs = [str(uuid4()) for _ in range(2)]
    keys = [tenant_prefix(org) + job + '/original.pdf' for job in jobs]
    objects = {key: b'synthetic document' for key in keys}

    class Storage:
        def delete(self, key):
            objects.pop(key, None)

    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as owner:
        owner.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD 'disposable-test-only'").format(sql.Identifier(role)))
        try:
            monkeypatch.setattr(settings, 'DATABASE_URL', TEST_DATABASE_URL)
            monkeypatch.setattr(sys, 'argv', ['provision_cleanup.py', role])
            runpy.run_path(str(Path(__file__).resolve().parents[2] / 'deploy/storage/provision_cleanup.py'))
            for job, key in zip(jobs, keys):
                owner.execute("INSERT INTO upload_intents(job_id,org_id,storage_key,status,lease_deadline) VALUES (%s,%s,%s,'uploading',clock_timestamp() - interval '1 hour')", (job, org, key))
            owner.execute("INSERT INTO extraction_jobs(job_id,org_id,status,storage_key) VALUES (%s,%s,'completed',%s)", (jobs[1], org, keys[1]))
            url = make_url(TEST_DATABASE_URL).set(drivername='postgresql+psycopg', username=role, password='disposable-test-only').render_as_string(hide_password=False)
            engine = create_engine(url)
            try:
                app = FastAPI()
                app.include_router(cleanup_maintenance.router)
                app.dependency_overrides[cleanup_maintenance.maintenance_token] = lambda: 'x' * 40
                monkeypatch.setattr(cleanup_maintenance, 'maintenance_factory', lambda: sessionmaker(bind=engine, autoflush=False))
                monkeypatch.setattr(cleanup_maintenance, 'storage_service', Storage())
                client = TestClient(app)
                headers = {'Authorization': 'Bearer ' + 'x' * 40}
                assert not owner.execute("SELECT has_table_privilege(%s, 'public.upload_intents', 'SELECT')", (role,)).fetchone()[0]
                assert client.post('/maintenance/cleanup', headers=headers).json() == {'processed': 1}
                assert keys[0] not in objects and keys[1] in objects
                assert owner.execute('SELECT status FROM upload_intents WHERE job_id=%s', (jobs[0],)).fetchone() == ('abandoned',)
                # The timed-out PUT may arrive after deletion; retain the tombstone and clean again.
                objects[keys[0]] = b'late synthetic document'
                owner.execute("UPDATE upload_intents SET next_cleanup_at=clock_timestamp() - interval '1 second' WHERE job_id=%s", (jobs[0],))
                assert client.post('/maintenance/cleanup', headers=headers).json() == {'processed': 1}
                assert keys[0] not in objects and keys[1] in objects
                assert owner.execute('SELECT status FROM upload_intents WHERE job_id=%s', (jobs[0],)).fetchone() == ('abandoned',)
                # A completing upload holds its intent row until the job commits.
                racing_job = str(uuid4())
                racing_key = tenant_prefix(org) + racing_job + '/original.pdf'
                jobs.append(racing_job)
                objects[racing_key] = b'concurrent synthetic document'
                owner.execute("INSERT INTO upload_intents(job_id,org_id,storage_key,status,lease_deadline) VALUES (%s,%s,%s,'uploading',clock_timestamp() + interval '2 seconds')", (racing_job, org, racing_key))
                with psycopg.connect(TEST_DATABASE_URL) as uploader:
                    uploader.execute("INSERT INTO extraction_jobs(job_id,org_id,status,storage_key) VALUES (%s,%s,'queued',%s)", (racing_job, org, racing_key))
                    assert uploader.execute("UPDATE upload_intents SET status='completed' WHERE job_id=%s AND status='uploading' AND lease_deadline > clock_timestamp() RETURNING job_id", (racing_job,)).fetchone()
                    time.sleep(2.1)
                    assert client.post('/maintenance/cleanup', headers=headers).json() == {'processed': 0}
                    assert racing_key in objects
                    uploader.commit()
                assert client.post('/maintenance/cleanup', headers=headers).json() == {'processed': 0}
                assert racing_key in objects
                # Both queues stay eligible: two scheduler calls must serve each.
                revoked_job, cleanup_id = str(uuid4()), str(uuid4())
                revoked_key = tenant_prefix(org) + revoked_job + '/original.pdf'
                jobs.append(revoked_job)
                objects[revoked_key] = b'revoked synthetic document'
                objects[keys[0]] = b'another late write'
                owner.execute("UPDATE upload_intents SET next_cleanup_at=clock_timestamp() - interval '1 second' WHERE job_id=%s", (jobs[0],))
                owner.execute("INSERT INTO extraction_jobs(job_id,org_id,status,storage_key,deleted_at) VALUES (%s,%s,'failed',%s,clock_timestamp())", (revoked_job, org, revoked_key))
                owner.execute("INSERT INTO storage_cleanup(cleanup_id,org_id,storage_key,job_id,next_attempt_at,attempts) VALUES (%s,%s,%s,%s,clock_timestamp() - interval '1 second',0)", (cleanup_id, org, revoked_key, revoked_job))
                assert client.post('/maintenance/cleanup', headers=headers).json() == {'processed': 1}
                assert client.post('/maintenance/cleanup', headers=headers).json() == {'processed': 1}
                assert keys[0] not in objects and revoked_key not in objects
            finally:
                engine.dispose()
        finally:
            owner.execute('DELETE FROM extraction_jobs WHERE job_id = ANY(%s)', (jobs,))
            owner.execute('DELETE FROM upload_intents WHERE job_id = ANY(%s)', (jobs,))
            owner.execute(sql.SQL('DROP OWNED BY {}').format(sql.Identifier(role)))
            owner.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(role)))
