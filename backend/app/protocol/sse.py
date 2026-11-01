"""Server-sent events wire format: `event: <name>` plus one JSON `data:` line per event."""

import json
from typing import Any

from pydantic import BaseModel


def format_sse(event: str, data: BaseModel | dict[str, Any]) -> str:
    payload = data.model_dump(mode="json") if isinstance(data, BaseModel) else data
    # json.dumps escapes newlines, so the data always stays on a single line.
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event}\ndata: {body}\n\n"
