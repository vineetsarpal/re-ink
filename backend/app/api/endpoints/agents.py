"""
Disabled legacy agent endpoints; permissions remain enforced.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.auth import require_permission
from app.core.tenancy import get_tenant_db
from app.schemas.agent import (
    AutomatedReviewRequest,
    AutomatedReviewResponse,
    GuidedIntakeRequest,
    GuidedIntakeResponse,
)

router = APIRouter()


@router.post("/intake", response_model=GuidedIntakeResponse, tags=["agents"])
async def run_guided_intake_agent(
    request: GuidedIntakeRequest,
    db: Session = Depends(get_tenant_db),
    _user=Depends(require_permission("document:upload")),
) -> GuidedIntakeResponse:
    """Run the guided contract intake agent against a completed extraction job."""
    raise HTTPException(status_code=503, detail="Guided intake is disabled for workflow extraction.")


@router.post("/review", response_model=AutomatedReviewResponse, tags=["agents"])
def run_automated_review_agent(
    request: AutomatedReviewRequest,
    db: Session = Depends(get_tenant_db),
    _user=Depends(require_permission("contract:read")),
) -> AutomatedReviewResponse:
    """Generate an automated review for an existing contract."""
    raise HTTPException(status_code=503, detail="Automated review is disabled for workflow extraction.")
