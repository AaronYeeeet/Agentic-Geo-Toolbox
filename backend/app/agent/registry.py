"""Tool registry.

Tools are plain Python functions registered via @tool(...). Each receives the
active Session as first argument plus keyword arguments validated by the LLM
against the declared JSON schema, and returns a ToolResult.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class ToolResult:
    # Text summary fed back to the LLM (keep it compact — no raw GeoJSON here).
    summary: str
    # Map layer descriptors to push to the frontend (from Layer.to_descriptor()).
    layers: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON schema (OpenAI function-calling format)
    func: Callable[..., ToolResult]


_REGISTRY: dict[str, Tool] = {}


def tool(name: str, description: str, parameters: dict[str, Any]):
    def decorator(func: Callable[..., ToolResult]) -> Callable[..., ToolResult]:
        _REGISTRY[name] = Tool(name=name, description=description,
                               parameters=parameters, func=func)
        return func

    return decorator


def get_tool(name: str) -> Tool:
    return _REGISTRY[name]


def all_tools() -> dict[str, Tool]:
    return dict(_REGISTRY)


def openai_schema() -> list[dict[str, Any]]:
    """Tool definitions in the format LiteLLM/OpenAI/Anthropic expect."""
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            },
        }
        for t in _REGISTRY.values()
    ]
