"""
Organization provisioning for zero-org users.

A user who belongs to no organization gets a token with no org_id, which the
resource endpoints reject. This endpoint gives such a user a dedicated
organization (named after their email) and a membership in it, so every user is
scoped to exactly one tenant. It is idempotent: a user who already belongs to an
org gets that org back rather than a second one.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from workos import WorkOSClient

from app.core.auth import CurrentUser, get_authenticated_user
from app.core.config import settings

router = APIRouter()


class ProvisionOrganizationResponse(BaseModel):
    organization_id: str


def _workos_client() -> WorkOSClient:
    """Build a server-side WorkOS client. Seam for tests to patch."""
    return WorkOSClient(
        api_key=settings.WORKOS_API_KEY,
        client_id=settings.WORKOS_CLIENT_ID,
    )


@router.post("/provision-organization", response_model=ProvisionOrganizationResponse)
def provision_organization(
    user: CurrentUser = Depends(get_authenticated_user),
) -> ProvisionOrganizationResponse:
    """Ensure the caller belongs to an organization, creating a dedicated one if not."""
    if not settings.WORKOS_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="Organization provisioning is not configured on this server.",
        )

    client = _workos_client()

    # Idempotent: reuse an existing membership rather than creating a duplicate org.
    existing = client.organization_membership.list_organization_memberships(
        user_id=user.user_id
    )
    if existing.data:
        return ProvisionOrganizationResponse(
            organization_id=existing.data[0].organization_id
        )

    workos_user = client.user_management.get_user(user.user_id)
    org = client.organizations.create_organization(name=workos_user.email)
    client.organization_membership.create_organization_membership(
        user_id=user.user_id, organization_id=org.id
    )
    return ProvisionOrganizationResponse(organization_id=org.id)
