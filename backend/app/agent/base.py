"""Agent interface. The scripted mock is implemented; an LLM agent can be added behind the same protocol."""

from collections.abc import AsyncIterator
from typing import Protocol
from uuid import uuid4

from app.agent.language import detect_language
from app.agent.texts import t
from app.config import Settings
from app.protocol.models import AgentEvent, ChatRequest, Done, ErrorEvent, RunStart


class Agent(Protocol):
    def run(self, request: ChatRequest) -> AsyncIterator[AgentEvent]:
        """Yield protocol events for one answer: run_start first, done last."""
        ...


class UnavailableAgent:
    """Stands in for agent modes that are not implemented yet (AGENT_MODE=llm)."""

    async def run(self, request: ChatRequest) -> AsyncIterator[AgentEvent]:
        detected = detect_language(request.messages[-1].content)
        lang = detected if detected in ("en", "de") else request.context.ui_language
        yield AgentEvent("run_start", RunStart(run_id=uuid4().hex))
        yield AgentEvent("error", ErrorEvent(message=t(lang, "error.llm_unavailable"), retryable=False))
        yield AgentEvent("done", Done())


def get_agent(settings: Settings) -> Agent:
    if settings.agent_mode == "mock":
        from app.agent.mock import MockAgent

        return MockAgent(fast=settings.mock_fast)
    return UnavailableAgent()
