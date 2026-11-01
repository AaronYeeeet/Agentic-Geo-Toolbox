"""POST /api/chat: streams the agent's answer as server-sent events."""

import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.agent.base import get_agent
from app.agent.texts import t
from app.config import get_settings
from app.protocol.models import ChatRequest, Done, ErrorEvent
from app.protocol.sse import format_sse

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/api/chat")
async def chat(request: ChatRequest) -> StreamingResponse:
    agent = get_agent(get_settings())

    async def stream() -> AsyncIterator[str]:
        finished = False
        try:
            async for event in agent.run(request):
                finished = event.event == "done"
                yield format_sse(event.event, event.data)
        except Exception:  # an agent bug must still end the stream cleanly for the UI
            logger.exception("agent run failed")
            if not finished:
                message = t(request.context.ui_language, "error.internal")
                yield format_sse("error", ErrorEvent(message=message, retryable=True))
                yield format_sse("done", Done())

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
