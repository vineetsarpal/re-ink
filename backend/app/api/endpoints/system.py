"""System-level endpoints for exposing runtime configuration."""
from fastapi import APIRouter
from pydantic import BaseModel

from app.core.config import settings


router = APIRouter()


class SystemConfigResponse(BaseModel):
    """Response payload describing frontend-relevant configuration flags."""

    agent_offline_mode: bool


@router.get("/config", response_model=SystemConfigResponse)
def get_system_config() -> SystemConfigResponse:
    """
    Return runtime configuration details needed by the frontend.
    """
    return SystemConfigResponse(agent_offline_mode=settings.AGENT_OFFLINE_MODE)
