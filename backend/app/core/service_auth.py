"""Narrow n8n machine identity; never confers WorkOS or approval permissions."""
from dataclasses import dataclass
from hmac import compare_digest
from typing import Iterator

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.database import SessionLocal


@dataclass(frozen=True)
class WorkflowServiceIdentity:
    org_id: str


_bearer = HTTPBearer(auto_error=False)


def require_workflow_service(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> WorkflowServiceIdentity:
    if not settings.workflow_configured:
        raise HTTPException(status_code=503, detail="Workflow integration unavailable")
    if (credentials is None or credentials.scheme.lower() != "bearer"
            or not compare_digest(credentials.credentials.encode(), settings.WORKFLOW_SERVICE_TOKEN.encode())):
        raise HTTPException(status_code=401, detail="Invalid workflow credential", headers={"WWW-Authenticate": "Bearer"})
    return WorkflowServiceIdentity(org_id=settings.WORKFLOW_CUSTOMER_ORG_ID)


def get_workflow_db(
    identity: WorkflowServiceIdentity = Depends(require_workflow_service),
) -> Iterator[Session]:
    db = SessionLocal()

    @event.listens_for(db, "after_begin")
    def _bind(session, transaction, connection):
        connection.exec_driver_sql("SELECT set_config('app.current_org', %s, true)", (identity.org_id,))
        connection.exec_driver_sql("SET LOCAL lock_timeout = '5s'")
        connection.exec_driver_sql("SET LOCAL statement_timeout = '15s'")

    try:
        yield db
    finally:
        event.remove(db, "after_begin", _bind)
        db.close()


def validate_worker_database_url(url: str) -> None:
    """Production worker startup gate; local database fixtures do not invoke it."""
    if not url:
        raise ValueError("WORKFLOW_WORKER_DATABASE_URL is required")
    parsed = make_url(url)
    if parsed.get_backend_name() != "postgresql" or parsed.query.get("sslmode") != "verify-full":
        raise ValueError("Worker PostgreSQL connection requires sslmode=verify-full")
    if not parsed.host or not parsed.username:
        raise ValueError("Worker connection requires a hostname and restricted identity")
