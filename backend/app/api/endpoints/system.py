"""System-level endpoints for exposing runtime configuration."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.config import settings
from app.core.auth import CurrentUser, get_current_user
from app.api.endpoints.provider_credentials import credentials_available


router = APIRouter()


class SystemConfigResponse(BaseModel):
    """Response payload describing frontend-relevant configuration flags."""

    agent_offline_mode: bool
    provider_credentials_enabled: bool
    trial_routing_enabled: bool


@router.get("/config", response_model=SystemConfigResponse)
def get_system_config(user: CurrentUser = Depends(get_current_user)) -> SystemConfigResponse:
    """
    Return runtime configuration details needed by the frontend.
    """
    return SystemConfigResponse(agent_offline_mode=settings.AGENT_OFFLINE_MODE,
                                provider_credentials_enabled=credentials_available(user),
                                trial_routing_enabled=settings.CLOUDFLARE_TRIAL_ENABLED)
