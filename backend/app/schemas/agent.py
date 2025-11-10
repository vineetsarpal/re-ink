"""
Pydantic schemas for agent-oriented endpoints (LangChain/LangGraph powered flows).
"""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field

from app.schemas.document import ReviewData
from app.schemas.contract import ContractWithParties


class AgentChatMessage(BaseModel):
    """Represents a single message in an agent conversation history."""

    role: Literal["system", "user", "assistant", "tool"]
    content: str = Field(..., min_length=1)


class GuidedIntakeRequest(BaseModel):
    """User request payload for the guided contract intake agent."""

    job_id: str = Field(..., description="Extraction job identifier to inspect.")
    user_input: str = Field(..., description="Latest user instruction or question.")
    chat_history: List[AgentChatMessage] = Field(
        default_factory=list,
        description="Prior conversation turns to maintain continuity."
    )


class GuidedIntakeAnalysis(BaseModel):
    """Structured output returned by the intake agent."""

    summary: str
    assistant_message: str
    missing_fields: List[str] = Field(default_factory=list)
    clarifying_questions: List[str] = Field(default_factory=list)
    recommended_next_steps: List[str] = Field(default_factory=list)
    confidence: Optional[float] = None


class GuidedIntakeResponse(BaseModel):
    """Agent response for guided contract intake workflows."""

    job_id: str
    status: Literal["ready", "awaiting_input", "job_not_ready", "error"]
    analysis: Optional[GuidedIntakeAnalysis] = None
    contract_data: Optional[Dict[str, Any]] = None
    parties_data: List[Dict[str, Any]] = Field(default_factory=list)
    suggested_review_payload: Optional[ReviewData] = None
    messages: List[AgentChatMessage] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)


class AutomatedReviewRequest(BaseModel):
    """Payload for the automated contract review agent."""

    contract_id: int
    user_input: str = Field(
        default="Generate a compliance summary and risk analysis.",
        description="Natural language instruction provided to the agent."
    )
    chat_history: List[AgentChatMessage] = Field(default_factory=list)


class ContractReviewAnalysis(BaseModel):
    """Structured review output including risk flags and recommendations."""

    summary: str
    assistant_message: str
    risk_flags: List[str] = Field(default_factory=list)
    recommended_actions: List[str] = Field(default_factory=list)
    compliance_notes: List[str] = Field(default_factory=list)
    confidence: Optional[float] = None


class AutomatedReviewResponse(BaseModel):
    """Response envelope for automated contract review runs."""

    contract_id: int
    status: Literal["complete", "not_found", "error"]
    analysis: Optional[ContractReviewAnalysis] = None
    contract_snapshot: Optional[ContractWithParties] = None
    messages: List[AgentChatMessage] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
