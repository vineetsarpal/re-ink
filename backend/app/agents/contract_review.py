"""
Automated contract review agent leveraging LangGraph orchestration.
Evaluates stored contract records and surfaces risks & recommendations.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langgraph.graph import END, StateGraph

from app.agents.utils import history_to_langchain_messages
from app.schemas.agent import AgentChatMessage, ContractReviewAnalysis


class ReviewState(TypedDict, total=False):
    """State container for the contract review graph."""

    contract_id: int
    contract_snapshot: Optional[Dict[str, Any]]
    user_input: str
    chat_history_messages: List[BaseMessage]
    status: str
    analysis: ContractReviewAnalysis
    assistant_message: str
    errors: List[str]


class AutomatedContractReviewAgent:
    """Runs a compliance- and risk-focused review for an existing contract."""

    def __init__(self, llm: BaseChatModel) -> None:
        self.llm = llm
        self.parser = PydanticOutputParser(pydantic_object=ContractReviewAnalysis)
        self.prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    (
                        "You are a reinsurance compliance analyst. "
                        "Review the contract snapshot and respond with a structured JSON payload "
                        "that summarises key points, flags risks, and recommends actions. "
                        "{format_instructions}"
                    ),
                ),
                MessagesPlaceholder(variable_name="chat_history"),
                ("system", "Contract snapshot (JSON):\n{contract_context}"),
                ("human", "{user_input}"),
            ]
        )
        self.chain = self.prompt | self.llm | self.parser

    def run(
        self,
        *,
        contract_id: int,
        contract_snapshot: Optional[Dict[str, Any]],
        user_input: str,
        chat_history: List[AgentChatMessage],
    ) -> ReviewState:
        state: ReviewState = {
            "contract_id": contract_id,
            "contract_snapshot": contract_snapshot,
            "user_input": user_input,
            "chat_history_messages": history_to_langchain_messages(chat_history),
            "errors": [],
        }
        graph = self._build_graph()
        return graph.invoke(state)

    # ------------------------------------------------------------------ #
    # Graph nodes
    # ------------------------------------------------------------------ #

    def _build_graph(self) -> StateGraph:
        builder = StateGraph(ReviewState)
        builder.add_node("validate", self._validate_contract)
        builder.add_node("analyse", self._analyse_contract)
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
    def _route_after_validation(state: ReviewState) -> str:
        if state.get("status") in {"error", "not_found"}:
            return "stop"
        return "analyse"

    def _validate_contract(self, state: ReviewState) -> ReviewState:
        if not state.get("contract_snapshot"):
            return {
                "status": "not_found",
                "errors": ["Contract not found. Provide a valid contract_id."],
            }
        return {"status": "ready"}

    def _analyse_contract(self, state: ReviewState) -> ReviewState:
        context = self._build_contract_context(state["contract_snapshot"])
        analysis = self.chain.invoke(
            {
                "chat_history": state.get("chat_history_messages", []),
                "contract_context": context,
                "user_input": state["user_input"],
                "format_instructions": self.parser.get_format_instructions(),
            }
        )
        return {
            "analysis": analysis,
            "assistant_message": analysis.assistant_message,
            "status": "complete",
        }

    @staticmethod
    def _build_contract_context(contract_snapshot: Dict[str, Any]) -> str:
        return json.dumps(contract_snapshot, default=str, indent=2)
