"""API router configuration."""
from fastapi import APIRouter, Depends

from app.api.endpoints import agents, contracts, parties, documents, review, system
from app.core.auth import get_current_user

api_router = APIRouter()

# Every resource router requires a valid WorkOS access token. The public
# endpoints (`/` and `/health`) live in app.main, outside this router.
_auth = [Depends(get_current_user)]

# Include all endpoint routers
api_router.include_router(
    documents.router,
    prefix="/documents",
    tags=["documents"],
    dependencies=_auth,
)
api_router.include_router(
    contracts.router,
    prefix="/contracts",
    tags=["contracts"],
    dependencies=_auth,
)
api_router.include_router(
    parties.router,
    prefix="/parties",
    tags=["parties"],
    dependencies=_auth,
)
api_router.include_router(
    review.router,
    prefix="/review",
    tags=["review"],
    dependencies=_auth,
)
api_router.include_router(
    agents.router,
    prefix="/agents",
    tags=["agents"],
    dependencies=_auth,
)
api_router.include_router(
    system.router,
    prefix="/system",
    tags=["system"],
    dependencies=_auth,
)
