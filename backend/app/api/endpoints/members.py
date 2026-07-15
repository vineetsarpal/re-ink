"""
Organization member-management endpoints backed by WorkOS.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from workos import WorkOSClient

from app.core.auth import CurrentUser, require_permission
from app.core.config import settings

router = APIRouter()


class MemberResponse(BaseModel):
    id: str
    user_id: str
    email: Optional[EmailStr] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    role: str


class MembersListResponse(BaseModel):
    members: list[MemberResponse]


class InviteMemberRequest(BaseModel):
    email: EmailStr
    role: str = "member"


class InviteMemberResponse(BaseModel):
    id: str
    email: EmailStr
    organization_id: str
    role: str


class UpdateMemberRoleRequest(BaseModel):
    role: str


class RemoveMemberResponse(BaseModel):
    message: str


def _workos_client() -> WorkOSClient:
    """Build a server-side WorkOS client. Seam for tests to patch."""
    return WorkOSClient(
        api_key=settings.WORKOS_API_KEY,
        client_id=settings.WORKOS_CLIENT_ID,
    )


def _role_slug(role) -> str:  # noqa: ANN001
    return getattr(role, "slug", role)


def _list_org_memberships(client: WorkOSClient, org_id: str):
    return client.organization_membership.list_organization_memberships(
        organization_id=org_id
    ).data


def _reject_if_last_admin_would_be_removed(
    memberships,
    *,
    target_membership_id: str,
    target_role: str | None = None,
) -> None:
    target = next(
        (
            membership
            for membership in memberships
            if membership.id == target_membership_id
        ),
        None,
    )
    if target is None or _role_slug(target.role) != "admin":
        return

    if target_role == "admin":
        return

    admin_count = sum(
        1 for membership in memberships if _role_slug(membership.role) == "admin"
    )
    if admin_count <= 1:
        raise HTTPException(
            status_code=409,
            detail="Cannot remove or demote the last admin.",
        )


def _member_response(membership) -> MemberResponse:  # noqa: ANN001
    user = getattr(membership, "user", None)
    return MemberResponse(
        id=membership.id,
        user_id=membership.user_id,
        email=getattr(user, "email", None),
        first_name=getattr(user, "first_name", None),
        last_name=getattr(user, "last_name", None),
        role=_role_slug(membership.role),
    )


def _configured_client() -> WorkOSClient:
    if not settings.WORKOS_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="WorkOS member management is not configured on this server.",
        )
    return _workos_client()


@router.get("/", response_model=MembersListResponse)
def list_members(
    user: CurrentUser = Depends(require_permission("member:manage")),
) -> MembersListResponse:
    """List members in the caller's organization."""
    client = _configured_client()
    memberships = _list_org_memberships(client, user.org_id)
    return MembersListResponse(
        members=[_member_response(membership) for membership in memberships]
    )


@router.post("/invitations", response_model=InviteMemberResponse, status_code=201)
def invite_member(
    request: InviteMemberRequest,
    user: CurrentUser = Depends(require_permission("member:manage")),
) -> InviteMemberResponse:
    """Invite a user into the caller's organization with a chosen role."""
    invitation = _configured_client().user_management.send_invitation(
        email=str(request.email),
        organization_id=user.org_id,
        role_slug=request.role,
        inviter_user_id=user.user_id,
    )
    return InviteMemberResponse(
        id=invitation.id,
        email=invitation.email,
        organization_id=invitation.organization_id,
        role=invitation.role_slug,
    )


@router.patch("/{membership_id}", response_model=MemberResponse)
def update_member_role(
    membership_id: str,
    request: UpdateMemberRoleRequest,
    user: CurrentUser = Depends(require_permission("member:manage")),
) -> MemberResponse:
    """Change an organization member's role."""
    client = _configured_client()
    memberships = _list_org_memberships(client, user.org_id)
    _reject_if_last_admin_would_be_removed(
        memberships,
        target_membership_id=membership_id,
        target_role=request.role,
    )
    updated = client.organization_membership.update_organization_membership(
        membership_id,
        role=request.role,
    )
    return _member_response(updated)


@router.delete("/{membership_id}", response_model=RemoveMemberResponse)
def remove_member(
    membership_id: str,
    user: CurrentUser = Depends(require_permission("member:manage")),
) -> RemoveMemberResponse:
    """Remove an organization member."""
    client = _configured_client()
    memberships = _list_org_memberships(client, user.org_id)
    _reject_if_last_admin_would_be_removed(
        memberships,
        target_membership_id=membership_id,
    )
    client.organization_membership.delete_organization_membership(membership_id)
    return RemoveMemberResponse(message="Member removed successfully")
