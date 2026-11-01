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
from ..workspace import Session
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


def run(session: Session, user_message: str) -> Iterator[dict[str, Any]]:
    """Drive one user turn. Yields event dicts and persists them as a trace."""
    trace: list[dict[str, Any]] = []
    trace_path = session.new_trace_path()
    started = time.monotonic()

    def emit(event: dict[str, Any]) -> dict[str, Any]:
        # The trace is rewritten after every event, so a running or aborted
        # turn is visible on disk too. "t" = seconds since the turn started.
        entry = {**event, "t": round(time.monotonic() - started, 1)}
        if event["type"] == "layer":  # geometry would bloat the trace (MBs per step)
            entry["layer"] = {k: v for k, v in event["layer"].items() if k != "geojson"}
        trace.append(entry)
        try:
            session.write_trace(trace, trace_path)
        except Exception:
            pass
        return event

    # Insert at 0: an upload before the first chat message already wrote to history.
    if not session.history or session.history[0]["role"] != "system":
        session.history.insert(0, {"role": "system", "content": SYSTEM_PROMPT})
    session.history.append({"role": "user", "content": user_message})
    yield emit({"type": "user", "content": user_message})

    try:
        for _ in range(settings.agent_max_steps):
            message = llm.complete(session.history, openai_schema())
            session.history.append(_assistant_to_dict(message))

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
        else:
            yield emit({"type": "assistant_message",
                        "content": "Reached the maximum number of steps for this task."})
    except Exception as exc:
        yield emit({"type": "error", "message": str(exc)})
    except GeneratorExit:  # browser closed the stream (reload, tab closed)
        emit({"type": "aborted"})
        raise
    yield emit({"type": "done"})
