"""Feature-gated scheduler endpoint for bounded tenant-safe R2 cleanup."""
from hmac import compare_digest

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.cleanup_worker import cleanup_next
from app.upload_reconciliation import reconcile_upload_next, upload_first
from app.services.storage_service import storage_service
from app.core.config import settings
from app.core.cloudflare_runtime import cleanup_factory, require_enabled

router = APIRouter()
_bearer = HTTPBearer(auto_error=False)


def maintenance_token() -> str:
    require_enabled()
    return settings.CLOUDFLARE_CLEANUP_TOKEN


def maintenance_factory():
    # Must use the dedicated cleanup database role when integration is enabled.
    return cleanup_factory()


def authorize(credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
              token: str = Depends(maintenance_token)) -> None:
    if len(token) < 32:
        raise HTTPException(503, "Storage cleanup is not configured")
    if (not credentials or credentials.scheme.lower() != "bearer" or
            len(credentials.credentials) > 512 or
            not compare_digest(credentials.credentials.encode(), token.encode())):
        raise HTTPException(401, "Invalid scheduler credential", headers={"WWW-Authenticate": "Bearer"})


@router.post("/maintenance/cleanup", dependencies=[Depends(authorize)])
def run_cleanup(response: Response):
    factory = maintenance_factory()
    try:
        # R2 operations can take 30 seconds. Bound each invocation to one item.
        first, second = ((reconcile_upload_next, cleanup_next) if upload_first(factory)
                         else (cleanup_next, reconcile_upload_next))
        processed = int(first(factory, storage_service) or second(factory, storage_service))
    except Exception:
        raise HTTPException(503, "Storage cleanup failed") from None
    response.headers["Cache-Control"] = "no-store"
    return {"processed": processed}
