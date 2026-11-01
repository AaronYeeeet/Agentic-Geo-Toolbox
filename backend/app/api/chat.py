"""Session + chat endpoints. Chat streams agent events as Server-Sent Events."""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from ..agent import models, orchestrator
from ..config import load_env_keys
from ..workspace import store

router = APIRouter()


class CreateSessionResponse(BaseModel):
    session_id: str


class ChatRequest(BaseModel):
    session_id: str
    message: str
    # Optional settings from the frontend; None = defaults from backend/.env.
    model: str | None = None
    max_steps: int | None = Field(default=None, ge=1, le=30)
    temperature: float | None = Field(default=None, ge=0, le=2)


def _session(session_id: str):
    try:
        return store.get(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


class SessionPatch(BaseModel):
    title: str = Field(min_length=1, max_length=120)


class LayerPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    visible: bool | None = None


@router.post("/sessions", response_model=CreateSessionResponse)
def create_session() -> CreateSessionResponse:
    session = store.create()
    return CreateSessionResponse(session_id=session.id)


@router.get("/sessions")
def list_sessions():
    """Saved chats, newest first (a new chat appears after its first message)."""
    return {"sessions": store.list()}


@router.get("/sessions/{session_id}")
def get_session(session_id: str):
    """Everything needed to reopen a chat: its turns (event logs) and layers."""
    session = _session(session_id)
    return {**session.meta(), "turns": session.turns(), "layers": session.layer_descriptors()}


@router.patch("/sessions/{session_id}")
def rename_session(session_id: str, patch: SessionPatch):
    _session(session_id)
    store.rename(session_id, patch.title)
    return store.get(session_id).meta()


@router.delete("/sessions/{session_id}")
def delete_session(session_id: str):
    _session(session_id)
    store.delete(session_id)
    return {"deleted": session_id}


@router.get("/sessions/{session_id}/history")
def get_history(session_id: str):
    """The full LLM context (system prompt, messages, tool results)."""
    return {"history": _session(session_id).history}


@router.get("/sessions/{session_id}/layers")
def get_layers(session_id: str):
    return {"layers": _session(session_id).layer_descriptors()}


@router.get("/sessions/{session_id}/layers/{layer_id}/geojson")
def get_layer_geojson(session_id: str, layer_id: str):
    """The layer's GeoJSON file as stored on disk (no parsing, so big layers are cheap)."""
    try:
        path = _session(session_id).layer_file(layer_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return FileResponse(path, media_type="application/geo+json")


@router.patch("/sessions/{session_id}/layers/{layer_id}")
def update_layer(session_id: str, layer_id: str, patch: LayerPatch):
    try:
        _session(session_id).update_layer(layer_id, name=patch.name, visible=patch.visible)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"ok": True}


@router.delete("/sessions/{session_id}/layers/{layer_id}")
def delete_layer(session_id: str, layer_id: str):
    try:
        _session(session_id).delete_layer(layer_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"deleted": layer_id}


@router.get("/models")
def list_models():
    return {"models": models.list_models()}


@router.post("/chat")
def chat(req: ChatRequest):
    session = _session(req.session_id)
    load_env_keys()  # a key added to .env works without a backend restart
    if req.model and not models.is_known(req.model):
        raise HTTPException(status_code=400, detail=f"Unknown model '{req.model}'")
    if req.model and models.missing_keys(req.model):
        keys = " or ".join(models.missing_keys(req.model))
        raise HTTPException(status_code=400,
                            detail=f"No API key for {req.model}: set {keys} in backend/.env")

    def event_stream():
        for event in orchestrator.run(session, req.message, req.model,
                                      req.max_steps, req.temperature):
            yield f"data: {json.dumps(event, default=str)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
