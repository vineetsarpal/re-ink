"""Read-only orphan organization report for manual reconciliation; run weekly.

Prints users with more than one organization, organizations with zero members,
and stale provisioning intents. It never creates, updates or deletes anything.
WorkOS and database credentials come from settings (environment / .env) at runtime.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))


def main():
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from workos import WorkOSClient

    from app.core.config import settings
    from app.services.orphan_org_report import orphan_org_report

    if not settings.WORKOS_API_KEY:
        raise ValueError('WORKOS_API_KEY is required')

    url = settings.DATABASE_URL.replace('postgresql://', 'postgresql+psycopg://', 1)
    engine = create_engine(url)
    try:
        with Session(engine) as db:
            report = orphan_org_report(
                WorkOSClient(api_key=settings.WORKOS_API_KEY, client_id=settings.WORKOS_CLIENT_ID),
                db,
                now=datetime.now(timezone.utc),
                stale_after=timedelta(hours=1),
            )
    finally:
        engine.dispose()

    print(f'Orphan organization report — {datetime.now(timezone.utc).isoformat(timespec="seconds")}')
    print('Read-only run; nothing is created, updated or deleted.\n')

    if not (report.multi_org_users or report.empty_orgs or report.stale_intents):
        print('All clear: no orphan organizations, duplicate memberships or stale intents.')

    print(f'Users with more than one organization ({len(report.multi_org_users)}):')
    for user in report.multi_org_users:
        print(f'  - {user.user_id} ({user.email or "email unavailable"}): '
              f'{", ".join(user.organization_ids)}')

    print(f'\nOrganizations with zero members ({len(report.empty_orgs)}):')
    for organization in report.empty_orgs:
        print(f'  - {organization.organization_id} ({organization.name or "unnamed"})')

    print(f'\nProvisioning intents not completed after one hour ({len(report.stale_intents)}):')
    for intent in report.stale_intents:
        updated = intent.updated_at.isoformat() if intent.updated_at else 'unknown'
        print(f'  - user {intent.user_id}: state={intent.state}, '
              f'org={intent.org_id or "not yet created"}, updated={updated}')


if __name__ == '__main__':
    main()
