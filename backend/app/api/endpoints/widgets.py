"""
WorkOS widget-token endpoint.

The frontend embeds WorkOS *widgets* (currently the User Profile widget) that
authenticate with a short-lived **widget session token** — distinct from the
SPA access token. That token can only be minted server-side with the
`WORKOS_API_KEY`, so this endpoint brokers it: it authorizes the caller via the
normal access-token dependency, then asks WorkOS for a widget token scoped to
the caller's organization and user.

User Profile is a self-service widget and requires no permission scope; other
widgets would pass their scope to `create_token`.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from workos import WorkOSClient

from app.core.auth import CurrentUser, get_current_user
from app.core.config import settings

router = APIRouter()


class WidgetTokenResponse(BaseModel):
    """A minted WorkOS widget session token (valid for ~1 hour)."""

    token: str


def _workos_client() -> WorkOSClient:
    """Build a server-side WorkOS client. Seam for tests to patch."""
    return WorkOSClient(
        api_key=settings.WORKOS_API_KEY,
        client_id=settings.WORKOS_CLIENT_ID,
    )


@router.post("/user-profile/token", response_model=WidgetTokenResponse)
def create_user_profile_token(
    user: CurrentUser = Depends(get_current_user),
) -> WidgetTokenResponse:
    """Mint a User Profile widget token for the signed-in user."""
    if not settings.WORKOS_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="WorkOS widget tokens are not configured on this server.",
        )
    if not user.org_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The signed-in user is not associated with an organization.",
        )

    response = _workos_client().widgets.create_token(
        organization_id=user.org_id,
        user_id=user.user_id,
        scopes=None,  # User Profile widget requires no permission scope.
    )
    return WidgetTokenResponse(token=response.token)
