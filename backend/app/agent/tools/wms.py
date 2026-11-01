"""WMS (Web Map Service) tools: inspect capabilities and add raster layers."""
from __future__ import annotations

from owslib.wms import WebMapService

from ...workspace import Session
from ..registry import ToolResult, tool


@tool(
    name="wms_capabilities",
    description="Query a WMS endpoint's GetCapabilities and list the available "
    "layer names, titles and bounding boxes. Call this before add_wms_layer "
    "when you don't know the exact layer name.",
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Base URL of the WMS service."}
        },
        "required": ["url"],
    },
)
def wms_capabilities(session: Session, url: str) -> ToolResult:
    wms = WebMapService(url)
    lines = []
    for name, layer in list(wms.contents.items())[:60]:
        lines.append(f"- {name}: {layer.title}")
    title = wms.identification.title if wms.identification else "WMS"
    return ToolResult(summary=f"WMS '{title}' layers (max 60 shown):\n" + "\n".join(lines))


@tool(
    name="add_wms_layer",
    description="Add a WMS layer as a raster overlay on the map. Use "
    "wms_capabilities first if unsure about the layer name.",
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Base URL of the WMS service."},
            "layers": {"type": "string", "description": "Comma-separated WMS layer name(s)."},
            "name": {"type": "string", "description": "Display name for the overlay."},
            "version": {"type": "string", "description": "WMS version, default '1.3.0'."},
            "format": {"type": "string", "description": "Image format, default 'image/png'."},
        },
        "required": ["url", "layers"],
    },
)
def add_wms_layer(session: Session, url: str, layers: str, name: str | None = None,
                  version: str = "1.3.0", format: str = "image/png") -> ToolResult:
    sep = "&" if "?" in url else "?"
    crs_param = "crs" if version >= "1.3.0" else "srs"
    tile_url = (
        f"{url}{sep}service=WMS&version={version}&request=GetMap"
        f"&layers={layers}&styles=&format={format}&transparent=true"
        f"&{crs_param}=EPSG:3857&width=256&height=256&bbox={{bbox-epsg-3857}}"
    )
    descriptor = {
        "id": f"wms_{abs(hash((url, layers))) % 10**8}",
        "name": name or f"WMS: {layers}",
        "source": "wms",
        "kind": "wms-raster",
        "tile_url": tile_url,
        "attribution": url,
    }
    descriptor = session.add_raster(descriptor)  # persisted with the session
    return ToolResult(
        summary=f"Added WMS layer(s) '{layers}' from {url} as a raster overlay "
                f"'{descriptor['id']}'.",
        layers=[descriptor],
    )
