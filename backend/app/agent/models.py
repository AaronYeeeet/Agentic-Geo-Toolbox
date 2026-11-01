"""Catalog of LLMs the user can pick in the frontend.

Combines a short curated list (direct provider APIs) with OpenRouter's free,
tool-calling models, which are fetched live because that list changes often.
A model is "available" when the key its provider needs is set in backend/.env;
keys never leave the backend.
"""
from __future__ import annotations

import time
from typing import Any

import litellm
import requests

from ..config import load_env_keys, settings

# Direct provider models known to work with the tool loop (see README).
_CURATED = [
    {"id": "gemini/gemini-3.5-flash", "name": "Gemini 3.5 Flash", "provider": "Google",
     "free": True, "note": "Free tier: 5/min, 20/day"},
    {"id": "groq/openai/gpt-oss-120b", "name": "GPT-OSS 120B", "provider": "Groq",
     "free": True, "note": "Free tier"},
    {"id": "anthropic/claude-opus-5-5", "name": "Claude Opus 5.5", "provider": "Anthropic",
     "free": False, "note": "Paid, best planning"},
    {"id": "anthropic/claude-sonnet-5-5", "name": "Claude Sonnet 5.5", "provider": "Anthropic",
     "free": False, "note": "Paid, cheaper"},
]

_OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
_OPENROUTER_TTL_S = 3600
_openrouter_cache: dict[str, Any] = {"at": 0.0, "models": []}


def _openrouter_free_models() -> list[dict[str, Any]]:
    """Free OpenRouter models that support tool calling (cached for an hour)."""
    if time.monotonic() - _openrouter_cache["at"] < _OPENROUTER_TTL_S:
        return _openrouter_cache["models"]
    try:
        data = requests.get(_OPENROUTER_MODELS_URL, timeout=10).json()["data"]
    except Exception:
        return _openrouter_cache["models"]  # keep the last good list when offline

    models = []
    for m in data:
        pricing = m.get("pricing") or {}
        free = m["id"].endswith(":free") or m["id"] == "openrouter/free" or (
            pricing.get("prompt") == "0" and pricing.get("completion") == "0")
        if free and "tools" in (m.get("supported_parameters") or []):
            models.append({
                "id": f"openrouter/{m['id']}",
                "name": m.get("name") or m["id"],
                "provider": "OpenRouter",
                "free": True,
                "context_length": m.get("context_length"),
                "note": "Picks a free model automatically" if m["id"] == "openrouter/free"
                        else "Free: 20/min, 50/day (1000/day with credits)",
            })
    # The auto router first, then alphabetically.
    models.sort(key=lambda x: (x["id"] != "openrouter/openrouter/free", x["name"].lower()))
    _openrouter_cache.update(at=time.monotonic(), models=models)
    return models


def missing_keys(model: str) -> list[str]:
    """Env vars `model` still needs (cheap check, no network)."""
    if settings.llm_api_base and model == settings.llm_model:
        return []  # local server (Ollama): the endpoint is all it needs
    env = litellm.validate_environment(model)
    return [] if env["keys_in_environment"] else env["missing_keys"]


def list_models() -> list[dict[str, Any]]:
    load_env_keys()  # pick up keys added to .env since the start
    models = [dict(m) for m in _CURATED] + _openrouter_free_models()
    if not any(m["id"] == settings.llm_model for m in models):
        models.insert(0, {"id": settings.llm_model, "name": settings.llm_model,
                          "provider": "Default (.env)", "free": None, "note": ""})
    for m in models:
        m["missing_keys"] = missing_keys(m["id"])
        m["available"] = not m["missing_keys"]
        m["default"] = m["id"] == settings.llm_model
    return models


def is_known(model: str) -> bool:
    """Only catalog models may be requested, so the browser can't pick arbitrary
    (possibly paid) model strings."""
    return model == settings.llm_model or any(m["id"] == model for m in list_models())
