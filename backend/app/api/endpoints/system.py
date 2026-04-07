"""System-level endpoints for exposing runtime configuration."""
from typing import List
from fastapi import APIRouter
from pydantic import BaseModel

from app.core.config import settings


router = APIRouter()

AVAILABLE_BACKENDS = ["landingai", "openai", "anthropic", "free"]


class SystemConfigResponse(BaseModel):
    """Response payload describing frontend-relevant configuration flags."""

    agent_offline_mode: bool
    available_backends: List[str]
    default_backend: str


@router.get("/config", response_model=SystemConfigResponse)
def get_system_config() -> SystemConfigResponse:
    """
    Return runtime configuration details needed by the frontend.
    """
    return SystemConfigResponse(
        agent_offline_mode=settings.AGENT_OFFLINE_MODE,
        available_backends=AVAILABLE_BACKENDS,
        default_backend=settings.EXTRACTION_BACKEND,
    )
