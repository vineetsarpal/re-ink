"""Run from backend: uv run python ../deploy/storage/reconcile_orphans.py [--delete]."""
import argparse
from datetime import datetime, timedelta, timezone
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from sqlalchemy import select
from app.core.config import settings
from app.core.tenancy import bind_session_to_org
from app.db.database import SessionLocal
from app.models.extraction_job import ExtractionJob
from app.models.workflow import StorageCleanup
from app.services.storage_service import storage_service


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--delete", action="store_true", help="Delete confirmed old unreferenced objects")
    parser.add_argument("--grace-hours", type=int, default=24)
    args = parser.parse_args()
    if args.grace_hours < 24 or not settings.WORKFLOW_CUSTOMER_ORG_ID:
        parser.error("A configured customer and at least 24 hours grace are required")
    org = settings.WORKFLOW_CUSTOMER_ORG_ID
    cutoff = datetime.now(timezone.utc) - timedelta(hours=args.grace_hours)
    # List is a durable inventory even if upload commit and immediate cleanup both failed.
    # Never infer an orphan from DB unavailability: every candidate needs a successful query.
    for key, modified in storage_service.list_objects(org):
        if modified >= cutoff:
            continue
        with SessionLocal() as db:
            bind_session_to_org(db, org)
            used = db.scalar(select(ExtractionJob.job_id).where(ExtractionJob.storage_key == key))
            cleanup = db.scalar(select(StorageCleanup.cleanup_id).where(StorageCleanup.storage_key == key))
            if used or cleanup:
                continue
        print(("delete " if args.delete else "candidate ") + key)
        if args.delete:
            storage_service.delete(key)


if __name__ == "__main__":
    main()
