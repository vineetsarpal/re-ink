"""
Service layer responsible for configuring LangChain/LangGraph agents
and exposing convenient run methods for API endpoints.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from pydantic import ValidationError
from sqlalchemy.orm import Session, joinedload

from app.agents.contract_review import AutomatedContractReviewAgent
from app.agents.guided_intake import GuidedContractIntakeAgent
from app.core.config import settings
from app.models.contract import Contract
from app.schemas.agent import (
    AgentChatMessage,
    AutomatedReviewRequest,
    AutomatedReviewResponse,
    ContractReviewAnalysis,
    GuidedIntakeAnalysis,
    GuidedIntakeRequest,
    GuidedIntakeResponse,
)
from app.schemas.contract import ContractCreate, ContractWithParties
from app.schemas.document import ReviewData
from app.schemas.party import PartyCreate
from app.services.extraction_store import extraction_store


class AgentConfigurationError(RuntimeError):
    """Raised when agent execution cannot proceed due to configuration issues."""


def _resolve_llm():
    """Instantiate the default chat model used by agents."""
    try:
        from langchain_openai import ChatOpenAI
    except ImportError as exc:  # pragma: no cover - only hit when deps missing
        raise AgentConfigurationError(
            "langchain-openai is required for agent execution. "
            "Install dependencies via `pip install langchain-openai`."
        ) from exc

    api_key = settings.OPENAI_API_KEY
    if not api_key:
        raise AgentConfigurationError(
            "OPENAI_API_KEY is not configured. Set it in backend/.env before running agents."
        )

    return ChatOpenAI(
        model=settings.AGENT_MODEL,
        temperature=settings.AGENT_TEMPERATURE,
        api_key=api_key,
    )


class AgentService:
    """Facade around guided intake and automated review agent executions."""

    def __init__(self) -> None:
        self._offline_mode = settings.AGENT_OFFLINE_MODE
        if self._offline_mode:
            self._llm = None
            self._init_error: Optional[AgentConfigurationError] = None
        else:
            try:
                self._llm = _resolve_llm()
                self._init_error = None
            except AgentConfigurationError as exc:
                self._llm = None
                self._init_error = exc

    def _ensure_ready(self) -> None:
        if self._offline_mode:
            return
        if self._init_error:
            raise self._init_error

    # ------------------------------------------------------------------ #
    # Guided contract intake
    # ------------------------------------------------------------------ #

    def run_guided_intake(self, request: GuidedIntakeRequest) -> GuidedIntakeResponse:
        job_payload = extraction_store.get_job(request.job_id)
        if self._offline_mode:
            return self._run_guided_intake_offline(request, job_payload)

        self._ensure_ready()
        agent = GuidedContractIntakeAgent(self._llm)

        try:
            state = agent.run(
                job_id=request.job_id,
                job_payload=job_payload,
                user_input=request.user_input,
                chat_history=request.chat_history,
            )
        except Exception as exc:  # pragma: no cover - safety net
            return GuidedIntakeResponse(
                job_id=request.job_id,
                status="error",
                errors=[f"Agent execution failed: {exc}"],
                messages=[
                    AgentChatMessage(
                        role="assistant",
                        content="I ran into an unexpected error while analysing the extraction results.",
                    )
                ],
            )

        analysis: Optional[GuidedIntakeAnalysis] = state.get("analysis")
        status = state.get("status", "error")
        assistant_content = state.get("assistant_message") or (
            "Extraction is still processing. I'll review once the job completes."
            if status == "job_not_ready"
            else "I could not review the extraction payload."
        )

        messages = list(request.chat_history)
        messages.append(AgentChatMessage(role="assistant", content=assistant_content))

        contract_data = None
        parties_data: List[dict] = []
        suggested_payload: Optional[ReviewData] = None
        payload_errors: List[str] = []

        if job_payload:
            parsed = job_payload.get("parsed_results") or {}
            contract_data = dict(parsed.get("contract_data") or {})
            parties_data = list(parsed.get("parties_data") or [])
            suggested_payload, payload_errors = self._build_review_payload(parsed)

        errors = list(state.get("errors", []))
        if payload_errors:
            errors.extend(payload_errors)

        return GuidedIntakeResponse(
            job_id=request.job_id,
            status=status,
            analysis=analysis,
            contract_data=contract_data,
            parties_data=parties_data,
            suggested_review_payload=suggested_payload,
            messages=messages,
            errors=errors,
        )

    def _build_review_payload(self, parsed_results: dict) -> Tuple[Optional[ReviewData], List[str]]:
        """Attempt to convert parsed extraction into ReviewData for auto-approval."""
        errors: List[str] = []
        contract_data = parsed_results.get("contract_data") or {}
        parties_data = parsed_results.get("parties_data") or []

        if not contract_data:
            errors.append("No contract data present in extraction payload.")
            return None, errors

        try:
            contract = ContractCreate(**contract_data)
        except ValidationError as exc:
            errors.append(f"Contract data validation failed: {exc}")
            return None, errors

        party_models = []
        for idx, party_dict in enumerate(parties_data):
            try:
                party_models.append(PartyCreate(**party_dict))
            except ValidationError as exc:
                errors.append(f"Party #{idx + 1} validation failed: {exc}")

        review_payload = ReviewData(
            contract=contract,
            parties=party_models,
            create_new_parties=True,
        )
        return review_payload, errors

    # ------------------------------------------------------------------ #
    # Automated contract review
    # ------------------------------------------------------------------ #

    def run_automated_review(
        self,
        db: Session,
        request: AutomatedReviewRequest,
    ) -> AutomatedReviewResponse:
        if self._offline_mode:
            return self._run_automated_review_offline(db, request)

        self._ensure_ready()
        contract = (
            db.query(Contract)
            .options(joinedload(Contract.parties))
            .filter(Contract.id == request.contract_id)
            .first()
        )

        if not contract:
            messages = list(request.chat_history)
            messages.append(
                AgentChatMessage(
                    role="assistant",
                    content="I could not find that contract. Please confirm the identifier.",
                )
            )
            return AutomatedReviewResponse(
                contract_id=request.contract_id,
                status="not_found",
                analysis=None,
                contract_snapshot=None,
                messages=messages,
                errors=["Contract not found"],
            )

        snapshot_model = ContractWithParties.model_validate(contract, from_attributes=True)
        contract_snapshot_dict = snapshot_model.model_dump()

        agent = AutomatedContractReviewAgent(self._llm)

        try:
            state = agent.run(
                contract_id=request.contract_id,
                contract_snapshot=contract_snapshot_dict,
                user_input=request.user_input,
                chat_history=request.chat_history,
            )
        except Exception as exc:  # pragma: no cover
            messages = list(request.chat_history)
            messages.append(
                AgentChatMessage(
                    role="assistant",
                    content="An unexpected error occurred while reviewing the contract.",
                )
            )
            return AutomatedReviewResponse(
                contract_id=request.contract_id,
                status="error",
                analysis=None,
                contract_snapshot=snapshot_model,
                messages=messages,
                errors=[f"Review agent failed: {exc}"],
            )

        analysis: Optional[ContractReviewAnalysis] = state.get("analysis")
        status = state.get("status", "complete")
        assistant_content = state.get("assistant_message") or "Review completed."

        messages = list(request.chat_history)
        messages.append(AgentChatMessage(role="assistant", content=assistant_content))

        return AutomatedReviewResponse(
            contract_id=request.contract_id,
            status=status,
            analysis=analysis,
            contract_snapshot=snapshot_model,
            messages=messages,
            errors=state.get("errors", []),
        )

    # ------------------------------------------------------------------ #
    # Offline helpers
    # ------------------------------------------------------------------ #

    def _run_guided_intake_offline(
        self,
        request: GuidedIntakeRequest,
        job_payload: Optional[dict],
    ) -> GuidedIntakeResponse:
        if not job_payload:
            messages = list(request.chat_history)
            messages.append(
                AgentChatMessage(
                    role="assistant",
                    content="Extraction job not found. Upload a document or seed a mock job first.",
                )
            )
            return GuidedIntakeResponse(
                job_id=request.job_id,
                status="job_not_ready",
                messages=messages,
                errors=["Extraction job not found. Upload a document first."],
            )

        status = job_payload.get("status")
        if status != "completed":
            messages = list(request.chat_history)
            messages.append(
                AgentChatMessage(
                    role="assistant",
                    content=f"Extraction job is '{status}'. Wait for completion before running the intake agent.",
                )
            )
            return GuidedIntakeResponse(
                job_id=request.job_id,
                status="job_not_ready",
                messages=messages,
                errors=[
                    f"Extraction job is '{status}'. Wait for completion before running the intake agent."
                ],
            )

        parsed = job_payload.get("parsed_results") or {}
        contract_data = dict(parsed.get("contract_data") or {})
        parties_data = list(parsed.get("parties_data") or [])
        suggested_payload, payload_errors = self._build_review_payload(parsed)

        analysis = self._offline_guided_analysis(contract_data, parties_data, request.user_input)
        assistant_message = analysis.assistant_message

        messages = list(request.chat_history)
        messages.append(AgentChatMessage(role="assistant", content=assistant_message))

        errors = payload_errors

        return GuidedIntakeResponse(
            job_id=request.job_id,
            status="ready",
            analysis=analysis,
            contract_data=contract_data,
            parties_data=parties_data,
            suggested_review_payload=suggested_payload,
            messages=messages,
            errors=errors,
        )

    def _offline_guided_analysis(
        self,
        contract_data: dict,
        parties_data: List[dict],
        user_input: str,
    ) -> GuidedIntakeAnalysis:
        required_fields = [
            "contract_number",
            "contract_name",
            "effective_date",
            "expiration_date",
            "premium_amount",
            "limit_amount",
        ]
        missing_fields = [
            field for field in required_fields if not contract_data.get(field)
        ]
        contract_name = contract_data.get("contract_name") or "the contract"
        party_count = len(parties_data)

        confident_score = max(0.3, 1.0 - 0.1 * len(missing_fields))

        clarifying_questions = [
            f"Can you confirm the value for {field.replace('_', ' ')}?"
            for field in missing_fields
        ]
        if not clarifying_questions:
            clarifying_questions.append(
                "Do you need any further adjustments before approving the extracted data?"
            )

        recommended_next_steps = [
            "Review extracted parties to verify contact details.",
            "Edit any incorrect contract fields in the review form before approval.",
        ]
        if missing_fields:
            recommended_next_steps.insert(
                0,
                "Fill in missing required fields highlighted above.",
            )

        summary = (
            f"Offline analysis for {contract_name}: {party_count} party records detected."
        )
        assistant_message = (
            f"{summary} Missing fields: {', '.join(missing_fields) if missing_fields else 'none'}."
            " This guidance is generated in offline mode."
        )

        return GuidedIntakeAnalysis(
            summary=summary,
            assistant_message=assistant_message,
            missing_fields=missing_fields,
            clarifying_questions=clarifying_questions,
            recommended_next_steps=recommended_next_steps,
            confidence=round(confident_score, 2),
        )

    def _run_automated_review_offline(
        self,
        db: Session,
        request: AutomatedReviewRequest,
    ) -> AutomatedReviewResponse:
        contract = (
            db.query(Contract)
            .options(joinedload(Contract.parties))
            .filter(Contract.id == request.contract_id)
            .first()
        )

        messages = list(request.chat_history)

        if not contract:
            messages.append(
                AgentChatMessage(
                    role="assistant",
                    content="I could not find that contract. Please confirm the identifier.",
                )
            )
            return AutomatedReviewResponse(
                contract_id=request.contract_id,
                status="not_found",
                messages=messages,
                errors=["Contract not found"],
            )

        snapshot_model = ContractWithParties.model_validate(contract, from_attributes=True)
        contract_snapshot_dict = snapshot_model.model_dump()

        analysis = self._offline_review_analysis(contract_snapshot_dict, request.user_input)
        messages.append(AgentChatMessage(role="assistant", content=analysis.assistant_message))

        return AutomatedReviewResponse(
            contract_id=request.contract_id,
            status="complete",
            analysis=analysis,
            contract_snapshot=snapshot_model,
            messages=messages,
            errors=[],
        )

    def _offline_review_analysis(
        self,
        contract_snapshot: dict,
        user_input: str,
    ) -> ContractReviewAnalysis:
        contract_name = contract_snapshot.get("contract_name") or "the contract"
        status = contract_snapshot.get("status") or "unknown"
        premium = contract_snapshot.get("premium_amount")
        retention = contract_snapshot.get("retention_amount")
        parties = contract_snapshot.get("parties") or []

        risk_flags: List[str] = []
        if status not in {"active", "pending_review"}:
            risk_flags.append(f"Contract status is '{status}'.")
        if not premium:
            risk_flags.append("Premium amount is missing.")
        if not retention:
            risk_flags.append("Retention amount is missing.")
        if not parties:
            risk_flags.append("No parties linked to the contract.")

        recommended_actions = [
            "Document any manual edits made during intake.",
            "Ensure regulatory reporting requirements are updated after approval.",
        ]
        if not parties:
            recommended_actions.insert(0, "Associate cedent and reinsurer parties before execution.")

        compliance_notes = [
            "Offline mode: review financial limits and commissions manually.",
            "Verify that the contract aligns with internal underwriting guidelines.",
        ]

        summary = (
            f"Offline review summary for {contract_name}: "
            f"{len(parties)} parties linked; status '{status}'."
        )
        assistant_message = (
            f"{summary} Risk flags: {', '.join(risk_flags) if risk_flags else 'none'}."
            " This assessment was generated without calling external LLMs."
        )

        confidence = 0.5 if risk_flags else 0.7

        return ContractReviewAnalysis(
            summary=summary,
            assistant_message=assistant_message,
            risk_flags=risk_flags,
            recommended_actions=recommended_actions,
            compliance_notes=compliance_notes,
            confidence=round(confidence, 2),
        )


# Singleton accessor
agent_service = AgentService()
