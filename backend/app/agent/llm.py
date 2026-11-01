"""Provider-agnostic LLM access via LiteLLM.

Swap Claude <-> Gemini <-> OpenRouter <-> local models through env vars
(LLM_MODEL / LLM_API_BASE) or per request from the frontend's model picker
— no code change. The rest of the system only depends on this thin wrapper.
"""
from __future__ import annotations

import re
import time
from typing import Any

import litellm

from ..config import settings  # also loads .env into os.environ (provider keys)
from . import models

litellm.drop_params = True  # tolerate provider-specific param differences
litellm.suppress_debug_info = True  # no "Provider List" banners on every retry

RATE_LIMIT_RETRIES = 3


def is_anthropic(model: str) -> bool:
    return model.startswith("anthropic/")


def missing_keys() -> list[str]:
    """Env vars the default model (LLM_MODEL) still needs."""
    return models.missing_keys(settings.llm_model)


def is_configured() -> bool:
    return not missing_keys()


def _is_daily_quota(exc: Exception) -> bool:
    # Gemini: "...RequestsPerDayPerProjectPerModel-FreeTier",
    # OpenRouter: "Rate limit exceeded: free-models-per-day".
    text = str(exc)
    return "PerDay" in text or "per-day" in text


def complete(messages: list[dict[str, Any]], tools: list[dict[str, Any]],
             model: str | None = None, temperature: float | None = None) -> Any:
    """One chat completion with tool-calling enabled. Returns the full response
    (message in .choices[0].message, token counts in .usage)."""
    model = model or settings.llm_model
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "tools": tools,
        "tool_choice": "auto",
        "max_tokens": 16000,
    }
    # Current Claude models (Sonnet/Opus 5.x) reject non-default sampling params
    # with a 400, so temperature is only sent to other models. Reproducibility
    # for Claude comes from the traces, not from sampling.
    if not is_anthropic(model):
        kwargs["temperature"] = 0 if temperature is None else temperature
    # LLM_API_BASE points at the local server of the default model (Ollama);
    # a model picked in the frontend talks to its provider's own endpoint.
    if settings.llm_api_base and model == settings.llm_model:
        kwargs["api_base"] = settings.llm_api_base

    # Free tiers allow only a few requests per minute (Gemini: 5/min,
    # OpenRouter: 20/min), and one agent turn needs one request per step.
    # On HTTP 429 wait as long as the provider asks ("retry in 7.6s"), then retry.
    for attempt in range(RATE_LIMIT_RETRIES + 1):
        try:
            return litellm.completion(**kwargs)
        except litellm.RateLimitError as exc:
            # A daily quota only resets hours later, so waiting is pointless.
            if _is_daily_quota(exc):
                hint = re.search(r"retry in (\d+h\d+m|\d+m)", str(exc))
                raise RuntimeError(
                    f"Daily free-tier quota of {model} is used up"
                    + (f" (resets in about {hint.group(1)})" if hint else "")
                    + ". Pick another model in the settings."
                ) from exc
            if attempt == RATE_LIMIT_RETRIES:
                raise RuntimeError(
                    f"{model} is rate-limited right now (free models are often busy "
                    f"upstream). Try again later or pick another model in the settings. "
                    f"Details: {str(exc)[:300]}"
                ) from exc
            match = re.search(r"retry in ([\d.]+)s", str(exc))
            time.sleep(min(float(match.group(1)) + 1, 65) if match else 20)
