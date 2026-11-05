"""
LangGraph-powered guided contract intake agent.
Transforms LandingAI extraction payloads into actionable guidance for reviewers.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langgraph.graph import END, StateGraph

from app.schemas.agent import GuidedIntakeAnalysis, AgentChatMessage
from app.agents.utils import history_to_langchain_messages


class IntakeState(TypedDict, total=False):
    """Graph state for guided intake runs."""

    job_id: str
    user_input: str
    chat_history_messages: List[BaseMessage]
    job_payload: Optional[Dict[str, Any]]
    status: str
    analysis: GuidedIntakeAnalysis
    assistant_message: str
    errors: List[str]


class GuidedContractIntakeAgent:
    """Agent that reviews extraction payloads and suggests next actions."""

    def __init__(self, llm: BaseChatModel) -> None:
        self.llm = llm
        self.parser = PydanticOutputParser(pydantic_object=GuidedIntakeAnalysis)
        self.prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    (
                        "You are a senior reinsurance underwriting analyst. "
                        "You help teammates validate AI-extracted contract details. "
                        "Analyse the extraction snapshot, highlight missing or low-confidence "
                        "fields, and propose next steps. "
                        "Respond strictly in JSON using the provided schema.\n"
                        "{format_instructions}"
                    ),
                ),
                MessagesPlaceholder(variable_name="chat_history"),
                (
                    "system",
                    "Extraction snapshot (JSON):\n{extraction_context}",
                ),
                ("human", "{user_input}"),
            ]
        )
        self.chain = self.prompt | self.llm | self.parser

    def run(
        self,
        *,
        job_id: str,
        job_payload: Optional[Dict[str, Any]],
        user_input: str,
        chat_history: List[AgentChatMessage],
    ) -> IntakeState:
        """Execute the graph and return the final state."""
        state: IntakeState = {
            "job_id": job_id,
            "user_input": user_input,
            "job_payload": job_payload,
            "chat_history_messages": history_to_langchain_messages(chat_history),
            "errors": [],
        }

        graph = self._build_graph()
        return graph.invoke(state)

    # --------------------------------------------------------------------- #
    # Graph definition
    # --------------------------------------------------------------------- #

    def _build_graph(self) -> StateGraph:
        builder = StateGraph(IntakeState)
        builder.add_node("validate", self._validate_job)
        builder.add_node("analyse", self._analyse_payload)
        builder.set_entry_point("validate")
        builder.add_conditional_edges(
            "validate",
            self._route_after_validation,
            {
                "analyse": "analyse",
                "stop": END,
            },
        )
        builder.add_edge("analyse", END)
        return builder.compile()

    @staticmethod
    def _route_after_validation(state: IntakeState) -> str:
        status = state.get("status")
        if status in {"error", "job_not_ready"}:
            return "stop"
        return "analyse"

    def _validate_job(self, state: IntakeState) -> IntakeState:
        job_payload = state.get("job_payload")
        if not job_payload:
            return {
                "status": "job_not_ready",
                "errors": ["Extraction job not found. Upload a document first."],
            }

        status = job_payload.get("status")
        if status != "completed":
            return {
                "status": "job_not_ready",
                "errors": [
                    f"Extraction job is '{status}'. Wait for completion before running the intake agent."
                ],
            }

        return {"status": "ready"}

    def _analyse_payload(self, state: IntakeState) -> IntakeState:
        job_payload = state.get("job_payload", {})
        extraction_context = self._build_extraction_context(job_payload)
        analysis = self.chain.invoke(
            {
                "chat_history": state.get("chat_history_messages", []),
                "extraction_context": extraction_context,
                "user_input": state["user_input"],
                "format_instructions": self.parser.get_format_instructions(),
            }
        )

        return {
            "analysis": analysis,
            "assistant_message": analysis.assistant_message,
            "status": "ready",
        }

    # --------------------------------------------------------------------- #
    # Helpers
    # --------------------------------------------------------------------- #

    @staticmethod
    def _build_extraction_context(job_payload: Dict[str, Any]) -> str:
        parsed = job_payload.get("parsed_results") or {}
        view = {
            "filename": job_payload.get("filename"),
            "status": job_payload.get("status"),
            "message": job_payload.get("message"),
            "confidence": parsed.get("confidence_score"),
            "contract_data": parsed.get("contract_data"),
            "parties_data": parsed.get("parties_data"),
            "metadata": parsed.get("extraction_metadata"),
        }
        return json.dumps(view, default=str, indent=2)
