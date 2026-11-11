import hashlib
import hmac
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert

from app.core.config import settings
from app.core.tenancy import bind_session_to_org
from app.models.extraction_quota import OrganizationQuota, TrialDomain, TrialUser

WEBMAIL_DOMAINS = frozenset(Path(__file__).with_name('webmail_domains.txt').read_text().split())


def trial_user_hash(user_id, key):
    if not key:
        raise ValueError('TRIAL_IDENTITY_HASH_KEY must be configured and retained across key rotations')
    return hmac.new(key.encode(), user_id.encode(), hashlib.sha256).hexdigest()


def assign_trial_eligibility(db, org_id, user_id, email):
    user_hash = trial_user_hash(user_id, settings.TRIAL_IDENTITY_HASH_KEY)
    domain = email.rsplit('@', 1)[1].strip().lower()
    work_domain = domain not in WEBMAIL_DOMAINS
    keys = [f'trial:user:{user_hash}'] + ([f'trial:domain:{domain}'] if work_domain else [])
    for key in sorted(keys):
        db.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))'), {'key': key})
    bind_session_to_org(db, org_id)
    if db.get(OrganizationQuota, org_id):
        return
    eligible = db.get(TrialUser, user_hash) is None and (not work_domain or db.get(TrialDomain, domain) is None)
    db.execute(insert(OrganizationQuota).values(org_id=org_id, trial_eligible=eligible,
        month=datetime.now(timezone.utc).date().replace(day=1), monthly_successes=0,
        monthly_attempts=0, pending=0, free_successes=0, free_pending=0))
    if eligible:
        db.add(TrialUser(user_hash=user_hash, org_id=org_id))
        if work_domain:
            db.add(TrialDomain(domain=domain, org_id=org_id))
    db.flush()
