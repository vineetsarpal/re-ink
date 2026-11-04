"""Public runtime capabilities; never expose service configuration."""
from fastapi import APIRouter
from pydantic import BaseModel
from app.core.config import settings

router = APIRouter()

class SystemConfigResponse(BaseModel):
    workflow_extraction_enabled: bool
    workflow_retry_available: bool
    guided_intake_enabled: bool = False
    automated_review_enabled: bool = False

@router.get('/config', response_model=SystemConfigResponse)
def get_system_config() -> SystemConfigResponse:
    enabled = settings.workflow_configured and settings.WORKFLOW_UPLOADS_ENABLED
    return SystemConfigResponse(
        workflow_extraction_enabled=enabled,
        workflow_retry_available=enabled,
    )
