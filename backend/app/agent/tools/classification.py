"""Surface classification tool — STUB.

This is a placeholder with a stable interface. Replace the body of
`_run_model` with a real inference call (e.g. a torchgeo/HuggingFace semantic
segmentation model over aerial imagery) without changing the tool signature or
the orchestrator. The stub returns a plausible class distribution so the rest of
the agent pipeline can be developed and demoed end-to-end.
"""
from __future__ import annotations

import hashlib

from ...workspace import Session
from ..registry import ToolResult, tool

_CLASSES = ["sealed/built-up", "vegetation", "water", "bare soil", "road"]


def _run_model(seed: str) -> dict[str, float]:
    """STUB: deterministic pseudo-distribution derived from the input."""
    h = hashlib.sha256(seed.encode()).digest()
    raw = [h[i] + 1 for i in range(len(_CLASSES))]
    total = sum(raw)
    return {c: round(v / total, 3) for c, v in zip(_CLASSES, raw)}


@tool(
    name="classify_surface",
    description="Run AI land-surface / land-cover classification over an area and "
    "return the share of each surface class (sealed, vegetation, water, soil, "
    "road). NOTE: currently a stub returning synthetic results; the interface is "
    "final and will be backed by a real model later.",
    parameters={
        "type": "object",
        "properties": {
            "layer_id": {
                "type": "string",
                "description": "Optional layer defining the area of interest.",
            },
            "bbox": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Optional [south, west, north, east] area of interest in WGS84.",
            },
        },
        "required": [],
    },
)
def classify_surface(session: Session, layer_id: str | None = None,
                     bbox: list[float] | None = None) -> ToolResult:
    if layer_id:
        aoi = f"layer:{layer_id}:{session.get_layer(layer_id).gdf.total_bounds.tolist()}"
    elif bbox:
        aoi = f"bbox:{bbox}"
    else:
        return ToolResult(summary="Provide either layer_id or bbox for classification.")

    dist = _run_model(aoi)
    breakdown = ", ".join(f"{c}: {p * 100:.1f}%" for c, p in dist.items())
    return ToolResult(
        summary=f"[STUB classification] Surface composition for {aoi}: {breakdown}. "
        "(Synthetic result — replace _run_model with a real model.)"
    )
