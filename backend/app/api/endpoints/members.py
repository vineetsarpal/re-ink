"""
Organization member-management endpoints backed by WorkOS.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy import text
from sqlalchemy.orm import Session
from workos import WorkOSClient

from app.core.auth import CurrentUser, get_current_user, require_permission
from app.core.config import settings
from app.db.database import get_db
from app.models.provisioning_intent import ProvisioningIntent

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


class LeaveOrganizationResponse(BaseModel):
    account_deleted: bool


def _workos_client() -> WorkOSClient:
    """Build a server-side WorkOS client. Seam for tests to patch."""
    return WorkOSClient(
        api_key=settings.WORKOS_API_KEY,
        client_id=settings.WORKOS_CLIENT_ID,
    )


def _role_slug(role) -> str:  # noqa: ANN001
    return getattr(role, "slug", role)


def _list_org_memberships(client: WorkOSClient, org_id: str):
    page = client.organization_membership.list_organization_memberships(
        organization_id=org_id
    )
    memberships = list(page.data)
    while isinstance(getattr(page, "after", None), str):
        page = client.organization_membership.list_organization_memberships(
            organization_id=org_id,
            after=page.after,
        )
        memberships.extend(page.data)
    return memberships


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
            detail=(
                "Cannot remove or demote the last admin. Promote another member to "
                "admin or close the organization first."
            ),
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


def _lock_org_memberships(db: Session, org_id: str) -> None:
    """Serialize membership changes per org until the transaction ends."""
    db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"reink:org-membership:{org_id}"},
    )


def _has_other_membership(client: WorkOSClient, user_id: str, membership_id: str) -> bool:
    after = None
    while True:
        kwargs = {"user_id": user_id, "statuses": ["active", "inactive", "pending"]}
        if after:
            kwargs["after"] = after
        page = client.organization_membership.list_organization_memberships(**kwargs)
        if any(membership.id != membership_id for membership in page.data):
            return True
        after = getattr(page, "after", None)
        if not isinstance(after, str):
            return False


@router.post("/me/leave", response_model=LeaveOrganizationResponse)
def leave_organization(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> LeaveOrganizationResponse:
    """Remove the caller's own membership and delete a now-orgless account."""
    client = _configured_client()
    try:
        _lock_org_memberships(db, user.org_id)
        memberships = _list_org_memberships(client, user.org_id)
        own_membership = next(
            (m for m in memberships if m.user_id == user.user_id),
            None,
        )
        if own_membership is None:
            raise HTTPException(
                status_code=404, detail="Organization membership not found."
            )
        _reject_if_last_admin_would_be_removed(
            memberships,
            target_membership_id=own_membership.id,
        )

        if _has_other_membership(client, user.user_id, own_membership.id):
            client.organization_membership.delete_organization_membership(
                own_membership.id
            )
            db.commit()
            return LeaveOrganizationResponse(account_deleted=False)

        intent = db.get(ProvisioningIntent, user.user_id)
        if intent is not None:
            db.delete(intent)
            db.flush()
        # Deleting the WorkOS user also removes its memberships.
        client.user_management.delete_user(user.user_id)
        db.commit()
        return LeaveOrganizationResponse(account_deleted=True)
    except Exception:
        db.rollback()
        raise


@router.patch("/{membership_id}", response_model=MemberResponse)
def update_member_role(
    membership_id: str,
    request: UpdateMemberRoleRequest,
    user: CurrentUser = Depends(require_permission("member:manage")),
    db: Session = Depends(get_db),
) -> MemberResponse:
    """Change an organization member's role."""
    client = _configured_client()
    try:
        _lock_org_memberships(db, user.org_id)
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
        db.commit()
    except Exception:
        db.rollback()
        raise
    return _member_response(updated)


@router.delete("/{membership_id}", response_model=RemoveMemberResponse)
def remove_member(
    membership_id: str,
    user: CurrentUser = Depends(require_permission("member:manage")),
    db: Session = Depends(get_db),
) -> RemoveMemberResponse:
    """Remove an organization member."""
    client = _configured_client()
    try:
        _lock_org_memberships(db, user.org_id)
        memberships = _list_org_memberships(client, user.org_id)
        _reject_if_last_admin_would_be_removed(
            memberships,
            target_membership_id=membership_id,
        )
        client.organization_membership.delete_organization_membership(membership_id)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return RemoveMemberResponse(message="Member removed successfully")
