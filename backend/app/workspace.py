"""In-memory session state + per-session workspace on disk.

Each session owns a set of named map *layers* (GeoDataFrames held in memory) and
a folder on disk for uploaded files and agent run traces. Layers are the shared
state that tools read from and write to, and that the frontend renders.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import geopandas as gpd

from .config import settings


@dataclass
class Layer:
    id: str
    name: str
    gdf: gpd.GeoDataFrame
    source: str = "generated"  # e.g. "osm", "upload", "buffer", ...

    def geometry_type(self) -> str:
        if self.gdf.empty:
            return "empty"
        geom_types = set(self.gdf.geom_type.dropna().unique())
        if geom_types & {"Polygon", "MultiPolygon"}:
            return "polygon"
        if geom_types & {"LineString", "MultiLineString"}:
            return "line"
        return "point"

    def to_descriptor(self) -> dict[str, Any]:
        """A JSON-serialisable layer description for the frontend (always WGS84)."""
        gdf = self.gdf
        if gdf.crs is not None and gdf.crs.to_epsg() != 4326:
            gdf = gdf.to_crs(epsg=4326)
        bounds = [float(x) for x in gdf.total_bounds] if not gdf.empty else None
        return {
            "id": self.id,
            "name": self.name,
            "source": self.source,
            "kind": "geojson",
            "geometry_type": self.geometry_type(),
            "feature_count": int(len(gdf)),
            "bounds": bounds,  # [minx, miny, maxx, maxy]
            "geojson": json.loads(gdf.to_json()),
        }


@dataclass
class Session:
    id: str
    layers: dict[str, Layer] = field(default_factory=dict)
    history: list[dict[str, Any]] = field(default_factory=list)  # LLM message log

    @property
    def dir(self) -> Path:
        d = settings.workspace_root / self.id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def add_layer(self, gdf: gpd.GeoDataFrame, name: str, source: str = "generated") -> Layer:
        layer_id = f"layer_{uuid.uuid4().hex[:8]}"
        if gdf.crs is None:
            gdf = gdf.set_crs(epsg=4326)
        layer = Layer(id=layer_id, name=name, gdf=gdf, source=source)
        self.layers[layer_id] = layer
        return layer

    def get_layer(self, layer_id: str) -> Layer:
        if layer_id not in self.layers:
            known = ", ".join(self.layers) or "(none)"
            raise KeyError(f"Unknown layer_id '{layer_id}'. Known layers: {known}")
        return self.layers[layer_id]

    def layer_catalog(self) -> str:
        """Short human/LLM-readable summary of available layers."""
        if not self.layers:
            return "(no layers yet)"
        lines = [
            f"- {lid}: '{l.name}' ({l.geometry_type()}, {len(l.gdf)} features, source={l.source})"
            for lid, l in self.layers.items()
        ]
        return "\n".join(lines)

    def new_trace_path(self) -> Path:
        traces = self.dir / "traces"
        traces.mkdir(exist_ok=True)
        return traces / f"trace_{int(time.time())}.json"

    def write_trace(self, events: list[dict[str, Any]], path: Path) -> Path:
        path.write_text(json.dumps(events, indent=2, default=str))
        return path


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    def create(self) -> Session:
        sid = f"sess_{uuid.uuid4().hex[:12]}"
        session = Session(id=sid)
        self._sessions[sid] = session
        return session

    def get(self, session_id: str) -> Session:
        if session_id not in self._sessions:
            raise KeyError(f"Unknown session '{session_id}'")
        return self._sessions[session_id]


store = SessionStore()
