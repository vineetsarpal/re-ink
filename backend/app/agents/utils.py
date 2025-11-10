"""
Utility helpers shared across agent implementations.
"""
from __future__ import annotations

from typing import List

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
)

from app.schemas.agent import AgentChatMessage


def history_to_langchain_messages(history: List[AgentChatMessage]) -> List[BaseMessage]:
    """Convert stored chat history to LangChain BaseMessage instances."""
    messages: List[BaseMessage] = []
    for item in history:
        role = item.role
        if role == "user":
            messages.append(HumanMessage(content=item.content))
        elif role == "assistant":
            messages.append(AIMessage(content=item.content))
        elif role == "system":
            messages.append(SystemMessage(content=item.content))
        else:
            # Fallback for tool/other roles
            messages.append(AIMessage(content=item.content))
    return messages


def langchain_message_to_agent(message: BaseMessage, role: str = "assistant") -> AgentChatMessage:
    """Convert LangChain message back into an AgentChatMessage."""
    content = getattr(message, "content", "")
    return AgentChatMessage(role=role, content=content)
