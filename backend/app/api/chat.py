"""Session + chat endpoints. Chat streams agent events as Server-Sent Events."""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..agent import orchestrator
from ..workspace import store

router = APIRouter()


class CreateSessionResponse(BaseModel):
    session_id: str


class ChatRequest(BaseModel):
    session_id: str
    message: str


@router.post("/sessions", response_model=CreateSessionResponse)
def create_session() -> CreateSessionResponse:
    session = store.create()
    return CreateSessionResponse(session_id=session.id)


@router.get("/sessions/{session_id}/layers")
def get_layers(session_id: str):
    try:
        session = store.get(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"layers": [layer.to_descriptor() for layer in session.layers.values()]}


@router.post("/chat")
def chat(req: ChatRequest):
    try:
        session = store.get(req.session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    def event_stream():
        for event in orchestrator.run(session, req.message):
            yield f"data: {json.dumps(event, default=str)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
