"""Provider-agnostic LLM access via LiteLLM.

Swap Claude <-> local models purely through env vars (LLM_MODEL / LLM_API_BASE)
— no code change. The rest of the system only depends on this thin wrapper.
"""
from __future__ import annotations

import re
import time
from typing import Any

import litellm

from ..config import settings  # also loads .env into os.environ (provider keys)

litellm.drop_params = True  # tolerate provider-specific param differences


def is_anthropic() -> bool:
    return settings.llm_model.startswith("anthropic/")


def missing_keys() -> list[str]:
    """Env vars the configured provider still needs (cheap check, no network)."""
    if settings.llm_api_base:
        return []  # local server (Ollama): the endpoint is all it needs
    env = litellm.validate_environment(settings.llm_model)
    return [] if env["keys_in_environment"] else env["missing_keys"]


def is_configured() -> bool:
    return not missing_keys()


def complete(messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> Any:
    """One chat completion with tool-calling enabled. Returns the message object."""
    kwargs: dict[str, Any] = {
        "model": settings.llm_model,
        "messages": messages,
        "tools": tools,
        "tool_choice": "auto",
        "max_tokens": 16000,
    }
    # Current Claude models (Sonnet/Opus 5.x) reject non-default sampling params
    # with a 400, so temperature=0 is only sent to local models. Reproducibility
    # for Claude comes from the traces, not from sampling.
    if not is_anthropic():
        kwargs["temperature"] = 0
    if settings.llm_api_base:
        kwargs["api_base"] = settings.llm_api_base

    # Free tiers allow only a few requests per minute (Gemini: 5/min), and one
    # agent turn needs one request per step. On HTTP 429 wait as long as the
    # provider asks ("retry in 7.6s"), then try again.
    for attempt in range(RATE_LIMIT_RETRIES + 1):
        try:
            response = litellm.completion(**kwargs)
            return response.choices[0].message
        except litellm.RateLimitError as exc:
            # A daily quota (Gemini free tier: 20 requests/day per model) only
            # resets hours later, so waiting is pointless: fail with a clear message.
            if "PerDay" in str(exc):
                hint = re.search(r"retry in (\d+h\d+m|\d+m)", str(exc))
                raise RuntimeError(
                    f"Daily free-tier quota of {settings.llm_model} is used up"
                    + (f" (resets in about {hint.group(1)})" if hint else "")
                    + ". Switch LLM_MODEL in backend/.env to another model or provider."
                ) from exc
            if attempt == RATE_LIMIT_RETRIES:
                raise
            match = re.search(r"retry in ([\d.]+)s", str(exc))
            time.sleep(min(float(match.group(1)) + 1, 65) if match else 20)


RATE_LIMIT_RETRIES = 3
