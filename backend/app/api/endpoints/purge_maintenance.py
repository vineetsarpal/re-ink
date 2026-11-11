"""Authenticated scheduler endpoint for resumable organization purge."""
from hmac import compare_digest
from time import monotonic

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from workos import WorkOSClient
from app.services.storage_service import storage_service
from app.purge_worker import purge_due
from app.core.config import settings
from app.core.cloudflare_runtime import purge_factory, require_enabled

router = APIRouter()
_bearer = HTTPBearer(auto_error=False)


def maintenance_token() -> str:
    require_enabled()
    return settings.CLOUDFLARE_PURGE_TOKEN


def maintenance_factory():
    return purge_factory()


def authorize(credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
              token: str = Depends(maintenance_token)) -> None:
    if len(token) < 32:
        raise HTTPException(503, "Organization purge is not configured")
    if (not credentials or credentials.scheme.lower() != "bearer" or
            len(credentials.credentials) > 512 or
            not compare_digest(credentials.credentials.encode(), token.encode())):
        raise HTTPException(401, "Invalid scheduler credential", headers={"WWW-Authenticate": "Bearer"})


def _workos_client():
    if not settings.WORKOS_API_KEY:
        raise RuntimeError('WorkOS is not configured')
    return WorkOSClient(api_key=settings.WORKOS_API_KEY, client_id=settings.WORKOS_CLIENT_ID,
                        request_timeout=5, max_retries=0)


@router.post("/maintenance/purge", dependencies=[Depends(authorize)])
def run_purge(response: Response):
    response.headers["Cache-Control"] = "no-store"
    try:
        processed = purge_due(maintenance_factory(), storage_service, _workos_client,
            settings.PURGE_BATCH_LIMIT, monotonic() + settings.PURGE_TIME_BUDGET_SECONDS)
    except Exception:
        raise HTTPException(503, 'Organization purge failed') from None
    return {"processed": processed}
