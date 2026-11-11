"""One-off legacy trial claims backfill; run with the migration-owner database URL."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))


def backfill_trial_eligibility(connection, workos, hash_key):
    from sqlalchemy import text
    from app.services.trial_eligibility import trial_user_hash, WEBMAIL_DOMAINS

    trial_user_hash('validate-configuration', hash_key)
    rows = connection.execute(text('''SELECT q.org_id, a.acknowledged_by FROM extraction_quota_org q
        LEFT JOIN provider_acknowledgments a ON a.org_id = q.org_id AND a.provider = 'landingai'
        WHERE q.free_successes > 0 OR q.free_pending > 0
        ORDER BY q.org_id''')).all()
    for org_id, user_id in rows:
        if not user_id:
            raise ValueError(f'Cannot backfill trial identity for {org_id}: missing provider acknowledgment')
        user_hash = trial_user_hash(user_id, hash_key)
        domain = workos.user_management.get_user(user_id).email.rsplit('@', 1)[1].strip().lower()
        connection.execute(text('INSERT INTO trial_users VALUES (:hash, :org) ON CONFLICT DO NOTHING'), {'hash': user_hash, 'org': org_id})
        if domain not in WEBMAIL_DOMAINS:
            connection.execute(text('INSERT INTO trial_domains VALUES (:domain, :org) ON CONFLICT DO NOTHING'), {'domain': domain, 'org': org_id})
    return len(rows)


def main():
    from sqlalchemy import create_engine
    from workos import WorkOSClient
    from app.core.config import settings

    if not settings.WORKOS_API_KEY or not settings.TRIAL_IDENTITY_HASH_KEY:
        raise ValueError('WORKOS_API_KEY and TRIAL_IDENTITY_HASH_KEY are required')
    url = settings.DATABASE_URL.replace('postgresql://', 'postgresql+psycopg://', 1)
    engine = create_engine(url)
    try:
        with engine.begin() as connection:
            count = backfill_trial_eligibility(connection, WorkOSClient(
                api_key=settings.WORKOS_API_KEY, client_id=settings.WORKOS_CLIENT_ID),
                settings.TRIAL_IDENTITY_HASH_KEY)
        print(f'Backfilled trial claims for {count} organizations')
    finally:
        engine.dispose()


if __name__ == '__main__':
    main()
