"""
Organization provisioning for zero-org users.

A user who belongs to no organization gets a token with no org_id, which the
resource endpoints reject. This endpoint gives such a user a dedicated
organization (named after their email) and a membership in it, so every user is
scoped to exactly one tenant. It is idempotent: a user who already belongs to an
org gets that org back rather than a second one.
"""
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, text
from sqlalchemy.orm import Session
from workos import WorkOSClient

from app.core.auth import CurrentUser, get_authenticated_user
from app.core.config import settings
from app.db.database import get_db
from app.services.trial_eligibility import assign_trial_eligibility
from app.models.provisioning_intent import ProvisioningIntent

router = APIRouter()


class ProvisionOrganizationResponse(BaseModel):
    organization_id: str


def _email_domain(email: str) -> str | None:
    """Return the normalized domain part of an email address."""
    if "@" not in email:
        return None
    domain = email.rsplit("@", 1)[1].strip().lower()
    return domain or None


def _domain_state_value(domain) -> str | None:  # noqa: ANN001
    state = getattr(domain, "state", None)
    return getattr(state, "value", state)


def _verified_domain_orgs(orgs, domain: str) -> list:  # noqa: ANN001
    matches = []
    for org in orgs:
        for org_domain in getattr(org, "domains", []):
            if (
                getattr(org_domain, "domain", "").lower() == domain
                and _domain_state_value(org_domain) == "verified"
            ):
                matches.append(org)
                break
    return matches


def _workos_client() -> WorkOSClient:
    """Build a server-side WorkOS client. Seam for tests to patch."""
    return WorkOSClient(
        api_key=settings.WORKOS_API_KEY,
        client_id=settings.WORKOS_CLIENT_ID,
    )


@router.post("/provision-organization", response_model=ProvisionOrganizationResponse)
def provision_organization(
    user: CurrentUser = Depends(get_authenticated_user),
    db: Session = Depends(get_db),
) -> ProvisionOrganizationResponse:
    """Ensure the caller belongs to an organization, creating a dedicated one if not."""
    if not settings.WORKOS_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="Organization provisioning is not configured on this server.",
        )

    intent = _locked_intent(db, user.user_id)
    if intent is None:
        db.add(ProvisioningIntent(user_id=user.user_id, intent_id=str(uuid4())))
        db.commit()

    client = _workos_client()
    while True:
        intent = _locked_intent(db, user.user_id)
        memberships = client.organization_membership.list_organization_memberships(user_id=user.user_id).data
        if intent.state == "completed":
            if any(member.organization_id == intent.org_id for member in memberships):
                return ProvisionOrganizationResponse(organization_id=intent.org_id)
            intent.organization_name = None
            if memberships:
                intent.org_id = memberships[0].organization_id
                org_id = intent.org_id
                db.commit()
                return ProvisionOrganizationResponse(organization_id=org_id)
            intent.intent_id = str(uuid4())
            intent.state = "pending"
            intent.org_id = None
            intent.created_at = func.now()
            db.commit()
            continue
        if intent.org_id:
            if not any(member.organization_id == intent.org_id for member in memberships):
                client.organization_membership.create_organization_membership(
                    user_id=user.user_id, organization_id=intent.org_id,
                    role="admin" if intent.organization_name else "viewer")
            if intent.organization_name:
                assign_trial_eligibility(db, intent.org_id, user.user_id, intent.organization_name)
            intent.state = "completed"
            org_id = intent.org_id
            db.commit()
            return ProvisionOrganizationResponse(organization_id=org_id)
        if memberships:
            intent.org_id = memberships[0].organization_id
            intent.state = "completed"
            org_id = intent.org_id
            db.commit()
            return ProvisionOrganizationResponse(organization_id=org_id)
        if intent.organization_name:
            org = client.organizations.create_organization(
                name=intent.organization_name,
                request_options={"idempotency_key": f"reink-provision-{intent.intent_id}"})
            intent.org_id = org.id
            intent.state = "org_created"
            db.commit()
            continue

        workos_user = client.user_management.get_user(user.user_id)
        if getattr(workos_user, "email_verified", False) is not True:
            raise HTTPException(403, "Verify your email before provisioning an organization.")
        domain = _email_domain(workos_user.email)
        verified_orgs = _verified_domain_orgs(
            client.organizations.list_organizations(domains=[domain]).data, domain) if domain else []
        if len(verified_orgs) == 1:
            intent.org_id = verified_orgs[0].id
            intent.state = "org_created"
        else:
            if not settings.TRIAL_IDENTITY_HASH_KEY:
                raise HTTPException(503, "Trial eligibility is not configured on this server.")
            intent.organization_name = workos_user.email
        db.commit()


def _locked_intent(db, user_id):
    db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
               {"key": f"reink:provision-organization:{user_id}"})
    return db.get(ProvisioningIntent, user_id, populate_existing=True)
