"""
Endpoints exposing LangChain/LangGraph powered agents.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.schemas.agent import (
    AutomatedReviewRequest,
    AutomatedReviewResponse,
    GuidedIntakeRequest,
    GuidedIntakeResponse,
)
from app.services.agent_service import AgentConfigurationError, agent_service

router = APIRouter()


@router.post("/intake", response_model=GuidedIntakeResponse, tags=["agents"])
async def run_guided_intake_agent(
    request: GuidedIntakeRequest,
) -> GuidedIntakeResponse:
    """Run the guided contract intake agent against a completed extraction job."""
    try:
        return agent_service.run_guided_intake(request)
    except AgentConfigurationError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/review", response_model=AutomatedReviewResponse, tags=["agents"])
def run_automated_review_agent(
    request: AutomatedReviewRequest,
    db: Session = Depends(get_db),
) -> AutomatedReviewResponse:
    """Generate an automated review for an existing contract."""
    try:
        return agent_service.run_automated_review(db=db, request=request)
    except AgentConfigurationError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
