"""Feature-gated machine transport for the Cloudflare extraction coordinator."""
from dataclasses import dataclass, field
from hmac import compare_digest
import json
from types import SimpleNamespace
from typing import Callable
from urllib.parse import quote

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.core.tenancy import bind_session_to_org
from app.core.config import settings, _decoded_secret
from app.core.cloudflare_runtime import machine_factory, require_enabled
from app.schemas.workflow import WorkflowPayloadError, parse_workflow_event
from app.models.cloudflare_execution import CloudflareExecution
from app.services.cloudflare_coordinator import claim_provider_call, checkpoint_terminal_event, authorize_provider_access
from app.services.workflow_service import get_attempt_credential, ingest_event
from app.services.workflow_service import _lock
from app.services.private_document_service import private_document_service as document_service
from app.services.dispatch_capability import InvalidCapability, verify_capability
from app.schemas.workflow import MAX_CALLBACK_BYTES


async def bounded_body(request):
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_CALLBACK_BYTES:
            raise HTTPException(413, "Request exceeds 5 MiB")
    return bytes(body)

router = APIRouter(prefix="/cloudflare", tags=["cloudflare-machine"])


@dataclass(frozen=True)
class CloudflareTransportSettings:
    worker_token: str = field(repr=False)
    capability_keys: list[bytes] = field(repr=False)


def transport_settings() -> CloudflareTransportSettings:
    require_enabled()
    keys = [_decoded_secret(settings.CLOUDFLARE_CAPABILITY_KEY)]
    if settings.CLOUDFLARE_PREVIOUS_CAPABILITY_KEY:
        keys.append(_decoded_secret(settings.CLOUDFLARE_PREVIOUS_CAPABILITY_KEY))
    return CloudflareTransportSettings(settings.CLOUDFLARE_MACHINE_TOKEN, keys)


def session_factory() -> Callable[[], Session]:
    return machine_factory()


def machine_org(
    job_id: str,
    attempt_id: str,
    authorization: str | None = Header(default=None),
    capability: str | None = Header(default=None, alias="X-Dispatch-Capability"),
    settings: CloudflareTransportSettings = Depends(transport_settings),
) -> str:
    if (len(settings.worker_token) < 32 or not settings.capability_keys or
            any(not isinstance(k, bytes) or len(k) < 32 for k in settings.capability_keys)):
        raise HTTPException(503, "Cloudflare extraction transport is not configured")
    scheme, _, value = (authorization or "").partition(" ")
    if (scheme.lower() != "bearer" or len(value) > 512 or not value or
            not compare_digest(value.encode(), settings.worker_token.encode())):
        raise HTTPException(401, "Invalid machine credentials")
    try:
        return verify_capability(capability, settings.capability_keys, job_id, attempt_id)
    except InvalidCapability:
        raise HTTPException(401, "Invalid machine credentials")


def machine_db(org_id: str = Depends(machine_org), factory: Callable[[], Session] = Depends(session_factory)):
    db = factory()

    @event.listens_for(db, "after_begin")
    def _bind(session, transaction, connection):
        connection.exec_driver_sql("SELECT set_config('app.current_org', %s, true)", (org_id,))
        connection.exec_driver_sql("SET LOCAL lock_timeout = '5s'")
        connection.exec_driver_sql("SET LOCAL statement_timeout = '15s'")

    try:
        # Also handles a test session whose transaction started before listener registration.
        bind_session_to_org(db, org_id)
        yield db
    finally:
        event.remove(db, "after_begin", _bind)
        db.close()


def _authorized_provider_access(db: Session, job_id: str, attempt_id: str, token: str) -> str:
    digest = authorize_provider_access(db, job_id, attempt_id, token)
    if digest is None:
        # Preserve deadline expiry and reservation release before responding.
        db.commit()
        raise HTTPException(409, "Attempt is no longer active")
    return digest


@router.post("/jobs/{job_id}/attempts/{attempt_id}/claim")
def claim(job_id: str, attempt_id: str, response: Response, db: Session = Depends(machine_db)):
    result = claim_provider_call(db, job_id, attempt_id)
    db.commit()
    response.headers["Cache-Control"] = "no-store"
    return result


@router.get("/jobs/{job_id}/attempts/{attempt_id}/credential")
def credential(job_id: str, attempt_id: str, response: Response,
               checkpoint_token: str | None = Header(default=None, alias="X-Checkpoint-Token"),
               db: Session = Depends(machine_db)):
    if not checkpoint_token or len(checkpoint_token) > 128:
        raise HTTPException(401, "Invalid checkpoint credential")
    digest = _authorized_provider_access(db, job_id, attempt_id, checkpoint_token)
    key = get_attempt_credential(db, job_id, attempt_id, digest)
    db.commit()
    if key is None:
        raise HTTPException(409, "Attempt is no longer active")
    response.headers["Cache-Control"] = "no-store"
    return {"api_key": key}


@router.get("/jobs/{job_id}/attempts/{attempt_id}/document")
def document(job_id: str, attempt_id: str,
             checkpoint_token: str | None = Header(default=None, alias="X-Checkpoint-Token"),
             db: Session = Depends(machine_db)):
    if not checkpoint_token or len(checkpoint_token) > 128:
        raise HTTPException(401, "Invalid checkpoint credential")
    _authorized_provider_access(db, job_id, attempt_id, checkpoint_token)
    job, _ = _lock(db, job_id, attempt_id, machine=True)
    snapshot = SimpleNamespace(**{name: getattr(job, name) for name in (
        "org_id", "storage_key", "size_bytes", "sha256", "filename", "content_type")})
    db.commit()
    data = document_service.read_original(snapshot)
    # Fence deletion, expiry, and terminal checkpoint while R2 was being read.
    _authorized_provider_access(db, job_id, attempt_id, checkpoint_token)
    db.commit()
    return Response(data, media_type=snapshot.content_type, headers={
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(snapshot.filename or 'document', safe='')}",
        "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


@router.post("/jobs/{job_id}/attempts/{attempt_id}/checkpoint")
async def checkpoint(job_id: str, attempt_id: str, request: Request, response: Response,
                     checkpoint_token: str | None = Header(default=None, alias="X-Checkpoint-Token"),
                     db: Session = Depends(machine_db)):
    if not checkpoint_token or len(checkpoint_token) > 128:
        raise HTTPException(401, "Invalid checkpoint credential")
    if request.headers.get("content-encoding", "identity").lower().strip() != "identity":
        raise HTTPException(413, "Compressed request bodies are unsupported")
    try:
        stored = checkpoint_terminal_event(db, job_id, attempt_id, checkpoint_token, await bounded_body(request))
    except WorkflowPayloadError as exc:
        raise HTTPException(exc.status_code, exc.detail)
    if stored is None:
        db.commit()
        raise HTTPException(409, "Attempt is no longer active")
    db.commit()
    response.headers["Cache-Control"] = "no-store"
    return {"stored": True}


@router.post("/jobs/{job_id}/attempts/{attempt_id}/deliver")
def deliver(job_id: str, attempt_id: str, response: Response, db: Session = Depends(machine_db)):
    # Only a previously validated, durable checkpoint can be delivered.
    _lock(db, job_id, attempt_id, machine=True)
    execution = db.get(CloudflareExecution, attempt_id)
    if execution is None or execution.terminal_event is None:
        raise HTTPException(409, "No terminal checkpoint available")
    body = json.dumps(execution.terminal_event, separators=(",", ":")).encode()
    result = ingest_event(db, parse_workflow_event(body), machine=True)
    db.commit()
    if "rejection" in result:
        raise HTTPException(result["rejection"], result["detail"])
    response.headers["Cache-Control"] = "no-store"
    return result
