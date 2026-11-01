"""Layer introspection and display tools."""
from __future__ import annotations

from ...workspace import Session
from ..registry import ToolResult, tool


@tool(
    name="list_layers",
    description="List all layers currently available in the session (id, name, "
    "geometry type, feature count). Use this to discover layer_ids before "
    "running processing tools.",
    parameters={"type": "object", "properties": {}, "required": []},
)
def list_layers(session: Session) -> ToolResult:
    return ToolResult(summary="Available layers:\n" + session.layer_catalog())


@tool(
    name="show_layer",
    description="(Re)render an existing layer on the map, e.g. after creating it "
    "or to bring the user's attention to it.",
    parameters={
        "type": "object",
        "properties": {
            "layer_id": {"type": "string", "description": "ID of the layer to display."}
        },
        "required": ["layer_id"],
    },
)
def show_layer(session: Session, layer_id: str) -> ToolResult:
    layer = session.get_layer(layer_id)
    return ToolResult(
        summary=f"Displayed layer '{layer.name}' ({len(layer.gdf)} features).",
        layers=[layer.to_descriptor()],
    )
