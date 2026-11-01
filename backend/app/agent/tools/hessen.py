"""Open-data discovery + generic geodata loading.

Open Data Hessen is federated into GovData.de, which exposes a standard CKAN
API. We search there (filtered to Hessen) and let the agent load any resulting
vector resource (GeoJSON/GML/WFS/GeoPackage/Shapefile-zip) by URL.
"""
from __future__ import annotations

import geopandas as gpd
import requests

from ...workspace import Session
from ..registry import ToolResult, tool

CKAN_SEARCH = "https://www.govdata.de/ckan/api/3/action/package_search"


@tool(
    name="search_open_data",
    description="Search official German open-data portals (GovData / Open Data "
    "Hessen) for datasets. Returns dataset titles and downloadable resource URLs "
    "(with formats). Follow up with load_geodata_from_url to load a vector resource.",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Free-text search, e.g. 'Radwege Darmstadt'."},
            "region": {
                "type": "string",
                "description": "Optional region filter, default 'Hessen'. Pass '' to search nationwide.",
            },
            "limit": {"type": "integer", "description": "Max datasets to return (default 5)."},
        },
        "required": ["query"],
    },
)
def search_open_data(session: Session, query: str, region: str = "Hessen",
                     limit: int = 5) -> ToolResult:
    q = f"{query} {region}".strip()
    resp = requests.get(CKAN_SEARCH, params={"q": q, "rows": limit}, timeout=30)
    resp.raise_for_status()
    results = resp.json().get("result", {}).get("results", [])
    if not results:
        return ToolResult(summary=f"No open-data datasets found for '{q}'.")

    lines = []
    for ds in results:
        lines.append(f"# {ds.get('title', ds.get('name'))}")
        for res in ds.get("resources", [])[:6]:
            fmt = (res.get("format") or "?").upper()
            lines.append(f"    [{fmt}] {res.get('url')}")
    return ToolResult(
        summary="Found datasets (use load_geodata_from_url on a vector URL):\n"
        + "\n".join(lines)
    )


@tool(
    name="load_geodata_from_url",
    description="Load a vector geodataset from a URL into a new map layer. "
    "Supports GeoJSON, GML, GeoPackage, Shapefile (.zip) and WFS GetFeature URLs.",
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Direct URL to the geodata resource."},
            "name": {"type": "string", "description": "Display name for the layer."},
        },
        "required": ["url"],
    },
)
def load_geodata_from_url(session: Session, url: str, name: str | None = None) -> ToolResult:
    gdf = gpd.read_file(url)
    if gdf.empty:
        return ToolResult(summary=f"Loaded 0 features from {url}.")
    if gdf.crs is None:
        gdf = gdf.set_crs(epsg=4326)
    layer = session.add_layer(gdf.to_crs(epsg=4326), name or url.split("/")[-1], source="opendata")
    return ToolResult(
        summary=f"Loaded {len(gdf)} features ({layer.geometry_type()}) from {url} "
        f"as layer '{layer.id}'.",
        layers=[layer.to_descriptor()],
    )
