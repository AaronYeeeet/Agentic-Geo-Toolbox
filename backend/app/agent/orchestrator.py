"""The agent loop: user message -> (LLM plans -> tool calls -> results)* -> answer.

Implemented as a synchronous generator that yields structured events. The API
layer turns these into Server-Sent Events for the frontend. Every run is also
persisted as a JSON trace for reproducibility.
"""
from __future__ import annotations

import json
import time
from typing import Any, Iterator

from ..config import settings
from ..workspace import Session, strip_geometry
from . import llm, tools  # noqa: F401  (importing tools registers them)
from .prompts import SYSTEM_PROMPT
from .registry import get_tool, openai_schema


def _assistant_to_dict(message: Any) -> dict[str, Any]:
    """Normalise a LiteLLM assistant message into a re-sendable dict."""
    out: dict[str, Any] = {"role": "assistant", "content": message.content or ""}
    # Claude thinks before tool calls; its thinking blocks must be sent back
    # unchanged in the next request, otherwise the tool loop can be rejected.
    if getattr(message, "thinking_blocks", None):
        out["thinking_blocks"] = message.thinking_blocks
    if getattr(message, "tool_calls", None):
        out["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.function.name, "arguments": tc.function.arguments},
            }
            for tc in message.tool_calls
        ]
    return out


def _execute_tool(session: Session, name: str, raw_args: str) -> Any:
    try:
        args = json.loads(raw_args) if raw_args else {}
    except json.JSONDecodeError as exc:
        from .registry import ToolResult
        return ToolResult(summary=f"ERROR: could not parse arguments ({exc}).")

    try:
        func = get_tool(name).func
    except KeyError:
        from .registry import ToolResult
        return ToolResult(summary=f"ERROR: unknown tool '{name}'.")

    try:
        return func(session, **args)
    except Exception as exc:  # surface tool errors to the LLM so it can recover
        from .registry import ToolResult
        return ToolResult(summary=f"ERROR running {name}: {exc}")


def _new_messages(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Messages added since the LLM last answered: what is new in this request.

    Thinking blocks are left out (long signatures); the reasoning text is shown
    with the response instead.
    """
    last = max((i for i, m in enumerate(history) if m["role"] == "assistant"), default=-1)
    return [{k: v for k, v in m.items() if k != "thinking_blocks"} for m in history[last + 1:]]


def _response_details(response: Any, message: Any) -> dict[str, Any]:
    usage = getattr(response, "usage", None)
    return {
        "content": message.content or "",
        "reasoning": getattr(message, "reasoning_content", None) or "",
        "tool_calls": [{"name": tc.function.name, "arguments": tc.function.arguments}
                       for tc in (getattr(message, "tool_calls", None) or [])],
        "finish_reason": getattr(response.choices[0], "finish_reason", None),
        "usage": {k: getattr(usage, k, None)
                  for k in ("prompt_tokens", "completion_tokens", "total_tokens")} if usage else None,
    }


def _close_open_tool_calls(session: Session) -> None:
    """After an error/abort, answer tool calls that never got a result.

    Providers reject a history in which an assistant tool call has no matching
    tool message, so without this a saved chat could not be continued.
    """
    answered = {m.get("tool_call_id") for m in session.history if m["role"] == "tool"}
    for m in session.history:
        for tc in m.get("tool_calls") or []:
            if tc["id"] not in answered:
                session.history.append({"role": "tool", "tool_call_id": tc["id"],
                                        "content": "ERROR: interrupted before the tool finished."})
                answered.add(tc["id"])


def run(session: Session, user_message: str, model: str | None = None,
        max_steps: int | None = None,
        temperature: float | None = None) -> Iterator[dict[str, Any]]:
    """Drive one user turn. Yields event dicts and persists them as a trace.

    model/max_steps/temperature come from the frontend settings; None means
    the defaults from backend/.env. Besides the chat events, every LLM call is
    reported as llm_request/llm_response, so the frontend can show what the
    model received and returned.
    """
    model = model or settings.llm_model
    max_steps = max_steps or settings.agent_max_steps
    trace: list[dict[str, Any]] = []
    trace_path = session.new_trace_path()
    started = time.monotonic()

    def emit(event: dict[str, Any]) -> dict[str, Any]:
        # The trace is rewritten after every event, so a running or aborted
        # turn is visible on disk too. "t" = seconds since the turn started.
        event = {**event, "t": round(time.monotonic() - started, 1)}
        trace.append(strip_geometry(event))  # geometry would bloat the trace (MBs per step)
        try:
            session.write_trace(trace, trace_path)
        except Exception:
            pass
        return event

    # Insert at 0: an upload before the first chat message already wrote to history.
    if not session.history or session.history[0]["role"] != "system":
        session.history.insert(0, {"role": "system", "content": SYSTEM_PROMPT})
    session.history.append({"role": "user", "content": user_message})
    session.save()
    # The settings are part of the trace, so runs stay comparable across models.
    yield emit({"type": "user", "content": user_message, "model": model,
                "max_steps": max_steps, "temperature": temperature})

    try:
        for step in range(1, max_steps + 1):
            schema = openai_schema()
            yield emit({"type": "llm_request", "step": step, "model": model,
                        "temperature": temperature,
                        "total_messages": len(session.history),
                        "new_messages": _new_messages(session.history),
                        "tools": [t["function"]["name"] for t in schema]})
            call_started = time.monotonic()
            response = llm.complete(session.history, schema, model, temperature)
            message = response.choices[0].message
            yield emit({"type": "llm_response", "step": step,
                        "duration_s": round(time.monotonic() - call_started, 1),
                        **_response_details(response, message)})
            session.history.append(_assistant_to_dict(message))
            session.save()

            tool_calls = getattr(message, "tool_calls", None)
            if not tool_calls:
                yield emit({"type": "assistant_message", "content": message.content or ""})
                break

            if message.content:
                yield emit({"type": "assistant_thought", "content": message.content})

            for tc in tool_calls:
                name = tc.function.name
                yield emit({"type": "tool_call", "name": name, "arguments": tc.function.arguments})

                result = _execute_tool(session, name, tc.function.arguments)

                for layer in result.layers:
                    yield emit({"type": "layer", "layer": layer})
                yield emit({"type": "tool_result", "name": name, "summary": result.summary})

                session.history.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result.summary,
                })
                session.save()
        else:
            yield emit({"type": "assistant_message",
                        "content": "Reached the maximum number of steps for this task."})
    except Exception as exc:
        _close_open_tool_calls(session)
        session.save()
        yield emit({"type": "error", "message": str(exc)})
    except GeneratorExit:  # browser closed the stream (reload, tab closed)
        _close_open_tool_calls(session)
        session.save()
        emit({"type": "aborted"})
        raise
    yield emit({"type": "done"})
