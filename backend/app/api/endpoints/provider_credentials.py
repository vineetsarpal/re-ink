"""Organization-admin controls for the LandingAI credential."""
import json

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.auth import CurrentUser, get_current_user, require_permission
from app.core.config import settings
from app.core.tenancy import get_tenant_db
from app.models.provider_credential import ProviderCredential
from app.models.provider_acknowledgment import LANDINGAI_NOTICE_VERSION, ProviderAcknowledgment
from app.services.provider_credentials import CredentialEncryptionError, encrypt_credential, credentials_available

router = APIRouter()
_PROVIDER = "landingai"
_MAX_BODY = 8192
_MAX_KEY = 4096
_VALIDATION_URL = "https://api.va.landing.ai/v1/ade/parse/jobs"


def require_credentials_available(user: CurrentUser = Depends(get_current_user)) -> None:
    if not credentials_available(user):
        raise HTTPException(503, "Customer provider keys are not available yet")


def validate_landingai_key(api_key: str) -> bool:
    """Check access without running a billable document extraction.

    A successful list request checks authentication, not extraction credits.
    Never log the request, response, or provider error body.
    """
    try:
        with httpx.Client(timeout=10, follow_redirects=False) as client:
            with client.stream("GET", _VALIDATION_URL, params={"pageSize": 1},
                               headers={"Authorization": f"Bearer {api_key}"}) as response:
                if response.status_code == 200:
                    return True
                if response.status_code in (401, 403):
                    return False
    except httpx.HTTPError:
        pass
    raise HTTPException(503, "LandingAI key could not be verified. Please try again.")


async def _read_api_key(request: Request) -> str:
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > _MAX_BODY:
            raise HTTPException(413, "Credential request too large")
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(422, "Invalid credential request") from None
    if not isinstance(payload, dict) or set(payload) != {"api_key"}:
        raise HTTPException(422, "Invalid credential request")
    value = payload["api_key"]
    if (not isinstance(value, str) or not value or len(value) > _MAX_KEY
            or not value.isascii() or any(ord(c) < 33 or ord(c) > 126 for c in value)):
        raise HTTPException(422, "Invalid API key format")
    return value


@router.get("/landingai")
def get_credential(response: Response, db: Session = Depends(get_tenant_db),
                   user: CurrentUser = Depends(require_permission("member:manage")),
                   _available: None = Depends(require_credentials_available)):
    response.headers["Cache-Control"] = "no-store"
    return {"configured": db.get(ProviderCredential, (user.org_id, _PROVIDER)) is not None}


@router.put("/landingai")
async def put_credential(request: Request, response: Response,
                         db: Session = Depends(get_tenant_db),
                         user: CurrentUser = Depends(require_permission("member:manage")),
                         _available: None = Depends(require_credentials_available)):
    api_key = await _read_api_key(request)
    try:
        ciphertext = encrypt_credential(api_key, user.org_id, _PROVIDER,
                                        settings.PROVIDER_CREDENTIAL_ENCRYPTION_KEY)
    except CredentialEncryptionError:
        raise HTTPException(503, "Credential storage is unavailable") from None
    if not await run_in_threadpool(validate_landingai_key, api_key):
        raise HTTPException(422, "LandingAI rejected this API key")
    statement = insert(ProviderCredential).values(org_id=user.org_id, provider=_PROVIDER, ciphertext=ciphertext)
    statement = statement.on_conflict_do_update(
        index_elements=[ProviderCredential.org_id, ProviderCredential.provider],
        set_={"ciphertext": statement.excluded.ciphertext, "updated_at": func.now()},
    )
    db.execute(statement)
    db.commit()
    response.headers["Cache-Control"] = "no-store"
    return {"configured": True}


@router.delete("/landingai", status_code=204)
def delete_credential(db: Session = Depends(get_tenant_db),
                      user: CurrentUser = Depends(require_permission("member:manage")),
                      _available: None = Depends(require_credentials_available)):
    row = db.get(ProviderCredential, (user.org_id, _PROVIDER))
    if row is not None:
        db.delete(row)
        db.commit()
    return Response(status_code=204, headers={"Cache-Control": "no-store"})


@router.get("/landingai/acknowledgment")
def get_acknowledgment(response: Response, db: Session = Depends(get_tenant_db),
                       user: CurrentUser = Depends(require_permission("document:upload")),
                       _available: None = Depends(require_credentials_available)):
    row = db.get(ProviderAcknowledgment, (user.org_id, _PROVIDER))
    response.headers["Cache-Control"] = "no-store"
    return {"acknowledged": row is not None and row.notice_version == LANDINGAI_NOTICE_VERSION}


@router.post("/landingai/acknowledgment")
def acknowledge_processing(response: Response, db: Session = Depends(get_tenant_db),
                           user: CurrentUser = Depends(require_permission("document:upload")),
                           _available: None = Depends(require_credentials_available)):
    statement = insert(ProviderAcknowledgment).values(
        org_id=user.org_id, provider=_PROVIDER, notice_version=LANDINGAI_NOTICE_VERSION,
        acknowledged_by=user.user_id,
    )
    statement = statement.on_conflict_do_update(
        index_elements=[ProviderAcknowledgment.org_id, ProviderAcknowledgment.provider],
        set_={"notice_version": LANDINGAI_NOTICE_VERSION, "acknowledged_by": user.user_id,
              "acknowledged_at": func.now()},
        where=ProviderAcknowledgment.notice_version != LANDINGAI_NOTICE_VERSION,
    )
    db.execute(statement)
    db.commit()
    response.headers["Cache-Control"] = "no-store"
    return {"acknowledged": True}


