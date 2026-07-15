"""
Tenant-admin endpoints for enterprise identity setup.
"""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from workos import WorkOSClient

from app.core.auth import CurrentUser, require_permission
from app.core.config import settings

router = APIRouter()

AdminPortalIntent = Literal["sso", "dsync", "domain_verification"]


class AdminPortalLinkRequest(BaseModel):
    intent: AdminPortalIntent


class AdminPortalLinkResponse(BaseModel):
    url: str


def _workos_client() -> WorkOSClient:
    """Build a server-side WorkOS client. Seam for tests to patch."""
    return WorkOSClient(
        api_key=settings.WORKOS_API_KEY,
        client_id=settings.WORKOS_CLIENT_ID,
    )


@router.post("/portal-link", response_model=AdminPortalLinkResponse)
def create_admin_portal_link(
    request: AdminPortalLinkRequest,
    user: CurrentUser = Depends(require_permission("sso:manage")),
) -> AdminPortalLinkResponse:
    """Mint a WorkOS Admin Portal link for the caller's organization."""
    if not settings.WORKOS_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="WorkOS Admin Portal links are not configured on this server.",
        )

    response = _workos_client().admin_portal.generate_link(
        organization=user.org_id,
        intent=request.intent,
    )
    return AdminPortalLinkResponse(url=response.link)
