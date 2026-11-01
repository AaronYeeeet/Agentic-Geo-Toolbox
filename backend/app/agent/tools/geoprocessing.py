"""Vector geoprocessing tools built on GeoPandas / Shapely.

Metric operations (buffer) reproject to a local UTM zone so distances are in
metres, then back to WGS84 for display.
"""
from __future__ import annotations

from ...workspace import Session
from ..registry import ToolResult, tool


def _layer_arg(desc: str) -> dict:
    return {"type": "string", "description": desc}


@tool(
    name="buffer",
    description="Create a buffer of a given distance (in metres) around all "
    "features of a layer. Returns a new polygon layer.",
    parameters={
        "type": "object",
        "properties": {
            "layer_id": _layer_arg("Layer to buffer."),
            "distance_m": {"type": "number", "description": "Buffer distance in metres."},
            "dissolve": {
                "type": "boolean",
                "description": "Merge overlapping buffers into one geometry (default false). "
                "Use true before measuring the covered area, otherwise overlaps are counted twice.",
            },
            "name": {"type": "string", "description": "Name for the resulting layer."},
        },
        "required": ["layer_id", "distance_m"],
    },
)
def buffer(session: Session, layer_id: str, distance_m: float, dissolve: bool = False,
           name: str | None = None) -> ToolResult:
    layer = session.get_layer(layer_id)
    gdf = layer.gdf.to_crs(layer.gdf.estimate_utm_crs())
    buffered = gdf[["geometry"]].copy() if dissolve else gdf.copy()
    buffered["geometry"] = gdf.buffer(distance_m)
    if dissolve:
        buffered = buffered.dissolve().explode(index_parts=False).reset_index(drop=True)
    result = session.add_layer(buffered.to_crs(epsg=4326),
                               name or f"{layer.name} buffer {distance_m}m", source="buffer")
    return ToolResult(
        summary=f"Buffered '{layer.name}' by {distance_m} m -> layer '{result.id}' "
        f"({len(result.gdf)} features).",
        layers=[result.to_descriptor()],
    )


@tool(
    name="clip",
    description="Clip a layer to the extent of a mask (polygon) layer. Returns "
    "the parts of the input that fall inside the mask as a new layer.",
    parameters={
        "type": "object",
        "properties": {
            "layer_id": _layer_arg("Layer to be clipped."),
            "mask_layer_id": _layer_arg("Polygon layer used as the clip mask."),
            "name": {"type": "string", "description": "Name for the resulting layer."},
        },
        "required": ["layer_id", "mask_layer_id"],
    },
)
def clip(session: Session, layer_id: str, mask_layer_id: str, name: str | None = None) -> ToolResult:
    import geopandas as gpd

    src = session.get_layer(layer_id).gdf.to_crs(epsg=4326)
    mask = session.get_layer(mask_layer_id).gdf.to_crs(epsg=4326)
    clipped = gpd.clip(src, mask)
    result = session.add_layer(clipped, name or f"clip of {layer_id}", source="clip")
    return ToolResult(
        summary=f"Clipped '{layer_id}' to '{mask_layer_id}' -> '{result.id}' "
        f"({len(result.gdf)} features).",
        layers=[result.to_descriptor()],
    )


@tool(
    name="intersection",
    description="Geometric intersection (overlay) of two layers. Returns the "
    "overlapping areas with attributes from both as a new layer.",
    parameters={
        "type": "object",
        "properties": {
            "layer_a": _layer_arg("First layer."),
            "layer_b": _layer_arg("Second layer."),
            "name": {"type": "string", "description": "Name for the resulting layer."},
        },
        "required": ["layer_a", "layer_b"],
    },
)
def intersection(session: Session, layer_a: str, layer_b: str, name: str | None = None) -> ToolResult:
    import geopandas as gpd

    a = session.get_layer(layer_a).gdf.to_crs(epsg=4326)
    b = session.get_layer(layer_b).gdf.to_crs(epsg=4326)
    out = gpd.overlay(a, b, how="intersection")
    result = session.add_layer(out, name or f"intersection {layer_a}∩{layer_b}", source="intersection")
    return ToolResult(
        summary=f"Intersection -> '{result.id}' ({len(result.gdf)} features).",
        layers=[result.to_descriptor()],
    )


@tool(
    name="centroids",
    description="Compute the centroid point of every feature in a layer. Returns "
    "a new point layer.",
    parameters={
        "type": "object",
        "properties": {
            "layer_id": _layer_arg("Layer whose feature centroids to compute."),
            "name": {"type": "string", "description": "Name for the resulting layer."},
        },
        "required": ["layer_id"],
    },
)
def centroids(session: Session, layer_id: str, name: str | None = None) -> ToolResult:
    layer = session.get_layer(layer_id)
    utm = layer.gdf.estimate_utm_crs()
    pts = layer.gdf.to_crs(utm).copy()
    pts["geometry"] = pts.centroid
    result = session.add_layer(pts.to_crs(epsg=4326), name or f"{layer.name} centroids", source="centroids")
    return ToolResult(
        summary=f"Computed {len(result.gdf)} centroids -> '{result.id}'.",
        layers=[result.to_descriptor()],
    )


@tool(
    name="layer_stats",
    description="Report summary statistics for a layer: feature count, geometry "
    "type, total area (km²) and/or total length (km), and bounding box.",
    parameters={
        "type": "object",
        "properties": {"layer_id": _layer_arg("Layer to summarise.")},
        "required": ["layer_id"],
    },
)
def layer_stats(session: Session, layer_id: str) -> ToolResult:
    layer = session.get_layer(layer_id)
    utm = layer.gdf.estimate_utm_crs()
    g = layer.gdf.to_crs(utm)
    parts = [f"Layer '{layer.name}' ({layer.id}): {len(g)} features, {layer.geometry_type()}."]
    gtype = layer.geometry_type()
    if gtype == "polygon":
        parts.append(f"Total area: {g.area.sum() / 1e6:.3f} km².")
    if gtype == "line":
        parts.append(f"Total length: {g.length.sum() / 1e3:.3f} km.")
    bounds = [round(float(x), 5) for x in layer.gdf.to_crs(epsg=4326).total_bounds]
    parts.append(f"Bounds (WGS84): {bounds}")
    return ToolResult(summary=" ".join(parts))
