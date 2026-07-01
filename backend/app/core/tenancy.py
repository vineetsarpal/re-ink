"""
Tenant scoping: carry the active organization into Postgres so RLS can enforce
isolation.

``bind_session_to_org`` sets the ``app.current_org`` GUC transaction-locally via
``set_config`` (the function form, since ``SET LOCAL`` cannot take bind params).
The RLS policies read it through ``current_setting('app.current_org', true)``.
"""
from __future__ import annotations

from typing import Iterator

from fastapi import Depends
from sqlalchemy import event, text
from sqlalchemy.orm import Session

from app.core.auth import CurrentUser, get_current_user
from app.db.database import SessionLocal


def bind_session_to_org(session: Session, org_id: str) -> None:
    """Bind ``session``'s current transaction to ``org_id`` for RLS enforcement."""
    session.execute(
        text("SELECT set_config('app.current_org', :org, true)"),
        {"org": org_id},
    )


def get_tenant_db(
    user: CurrentUser = Depends(get_current_user),
) -> Iterator[Session]:
    """Yield a DB session scoped to the caller's organization.

    The org GUC is re-applied on every transaction via an ``after_begin``
    listener, so it survives mid-request commits (endpoints commit then refresh)
    and always fails closed if a query somehow runs unbound.
    """
    db = SessionLocal()
    org_id = user.org_id

    @event.listens_for(db, "after_begin")
    def _bind(session, transaction, connection):  # noqa: ANN001
        connection.exec_driver_sql(
            "SELECT set_config('app.current_org', %s, true)", (org_id,)
        )

    try:
        yield db
    finally:
        event.remove(db, "after_begin", _bind)
        db.close()
