"""API router configuration."""
from fastapi import APIRouter
from app.api.endpoints import agents, contracts, parties, documents, review, system

api_router = APIRouter()

# Include all endpoint routers
api_router.include_router(
    documents.router,
    prefix="/documents",
    tags=["documents"]
)
api_router.include_router(
    contracts.router,
    prefix="/contracts",
    tags=["contracts"]
)
api_router.include_router(
    parties.router,
    prefix="/parties",
    tags=["parties"]
)
api_router.include_router(
    review.router,
    prefix="/review",
    tags=["review"]
)
api_router.include_router(
    agents.router,
    prefix="/agents",
    tags=["agents"]
)
api_router.include_router(
    system.router,
    prefix="/system",
    tags=["system"]
)
