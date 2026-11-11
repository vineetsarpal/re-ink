"""Feature-gated scheduler endpoint for bounded cross-tenant expiry maintenance."""
from hmac import compare_digest

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.expiry_worker import expire_next
from app.core.config import settings
from app.core.cloudflare_runtime import expiry_factory, require_enabled

router = APIRouter()
_bearer = HTTPBearer(auto_error=False)
_MAX_PER_CALL = 10


def maintenance_token() -> str:
    require_enabled()
    return settings.CLOUDFLARE_EXPIRY_TOKEN


def maintenance_factory():
    return expiry_factory()


def authorize(credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
              token: str = Depends(maintenance_token)) -> None:
    if (not token or not credentials or credentials.scheme.lower() != "bearer"
            or not compare_digest(credentials.credentials.encode(), token.encode())):
        raise HTTPException(401, "Invalid scheduler credential", headers={"WWW-Authenticate": "Bearer"})


@router.post("/maintenance/expiry", dependencies=[Depends(authorize)])
def run_expiry(response: Response):
    factory = maintenance_factory()
    processed = 0
    try:
        for _ in range(_MAX_PER_CALL):
            # Finish each transaction before touching a different job: this
            # preserves the lock ordering used by quota settlement.
            with factory.begin() as db:
                worked = expire_next(db)
            if not worked:
                break
            processed += 1
    except Exception:
        raise HTTPException(503, "Expiry maintenance failed") from None
    response.headers["Cache-Control"] = "no-store"
    return {"processed": processed}
