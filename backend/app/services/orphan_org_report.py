"""Read-only orphan organization report; never creates, updates or deletes anything."""
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.provisioning_intent import ProvisioningIntent

_PAGE_SIZE = 100


@dataclass
class MultiOrgUser:
    user_id: str
    email: str | None
    organization_ids: list[str] = field(default_factory=list)


@dataclass
class EmptyOrg:
    organization_id: str
    name: str | None


@dataclass
class OrphanOrgReport:
    multi_org_users: list[MultiOrgUser]
    empty_orgs: list[EmptyOrg]
    stale_intents: list[ProvisioningIntent]


def _paginated(fetch, **params):
    """Yield every item across the pages of a WorkOS list call."""
    params.setdefault("limit", _PAGE_SIZE)
    while True:
        page = fetch(**params)
        yield from page.data
        after = getattr(page, "after", None)
        if after is None or not page.data:
            return
        params["after"] = after


def orphan_org_report(workos_client, db: Session, *, now: datetime,
                      stale_after: timedelta = timedelta(hours=1)) -> OrphanOrgReport:
    """Surface duplicate memberships, memberless organizations and stale intents.

    WorkOS is read through list/get calls only and the database only through
    SELECTs; reconciliation is manual. Errors propagate rather than being read
    as absence.
    """
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")

    membership_counts: dict[str, int] = {}
    user_orgs: dict[str, set[str]] = {}
    orgs = []
    for org in _paginated(workos_client.organizations.list_organizations):
        orgs.append(org)
        for membership in _paginated(
            workos_client.organization_membership.list_organization_memberships,
            organization_id=org.id,
        ):
            membership_counts[org.id] = membership_counts.get(org.id, 0) + 1
            user_orgs.setdefault(membership.user_id, set()).add(org.id)

    multi_org_users = []
    for user_id in sorted(user_orgs):
        if len(user_orgs[user_id]) < 2:
            continue
        multi_org_users.append(MultiOrgUser(
            user_id=user_id,
            email=workos_client.user_management.get_user(user_id).email,
            organization_ids=sorted(user_orgs[user_id]),
        ))

    empty_orgs = [
        EmptyOrg(organization_id=org.id, name=org.name)
        for org in orgs if membership_counts.get(org.id, 0) == 0
    ]

    stale_intents = list(db.scalars(select(ProvisioningIntent).where(
        ProvisioningIntent.state != "completed",
        ProvisioningIntent.updated_at < now - stale_after,
    ).order_by(ProvisioningIntent.updated_at)))

    return OrphanOrgReport(
        multi_org_users=multi_org_users, empty_orgs=empty_orgs, stale_intents=stale_intents
    )
