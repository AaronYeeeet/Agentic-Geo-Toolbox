"""Sessions: map layers + LLM history, kept in memory and persisted to disk.

Each session owns a set of named map *layers* (GeoDataFrames, plus WMS raster
overlays) that tools read from and write to and that the frontend renders.
Everything is mirrored into the session folder, so sessions survive a backend
restart and old chats can be reopened:

    workspace/<session_id>/
        meta.json            title, created, updated
        history.json         LLM message log (what the model sees)
        layers/index.json    layer order, names, visibility, WMS descriptors
        layers/<id>.geojson  vector layer data (WGS84)
        traces/trace_*.json  one event log per user turn / upload
        uploads/             user-supplied files
"""
from __future__ import annotations

import json
import re
import shutil
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import geopandas as gpd

from .config import settings

_SESSION_ID = re.compile(r"^sess_[0-9a-f]{12}$")  # also guards against path traversal
TITLE_MAX = 60


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str, ensure_ascii=False))
    tmp.replace(path)  # atomic: a crash never leaves a half-written file


def _trace_sort_key(path: Path) -> int:
    digits = re.sub(r"\D", "", path.stem)
    stamp = int(digits) if digits else 0
    return stamp * 1000 if stamp < 10**11 else stamp  # old traces used seconds, new ones ms


def strip_geometry(event: dict[str, Any]) -> dict[str, Any]:
    """Drop GeoJSON from a layer event (traces keep only layer metadata)."""
    if event.get("type") == "layer" and isinstance(event.get("layer"), dict):
        return {**event, "layer": {k: v for k, v in event["layer"].items() if k != "geojson"}}
    return event


def _geometry_type(gdf: gpd.GeoDataFrame) -> str:
    if gdf.empty:
        return "empty"
    geom_types = set(gdf.geom_type.dropna().unique())
    if geom_types & {"Polygon", "MultiPolygon"}:
        return "polygon"
    if geom_types & {"LineString", "MultiLineString"}:
        return "line"
    return "point"


def write_geojson(gdf: gpd.GeoDataFrame, path: Path) -> None:
    """Write WGS84 GeoJSON without null properties.

    OSM layers have hundreds of sparse tag columns; with na="null" every
    feature repeats all of them as null, which turned 32k buildings into a
    300 MB file. na="drop" keeps only the tags a feature actually has.
    """
    if gdf.crs is not None and gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(epsg=4326)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(gdf.to_json(na="drop", default=str))  # str: dates read back by GDAL
    tmp.replace(path)


class Layer:
    """A vector layer. Its data lives in layers/<id>.geojson; the GeoDataFrame
    is read from there only when a tool needs it, so opening a chat with big
    layers stays fast. Count, type and bounds are kept as metadata."""

    def __init__(self, id: str, name: str, path: Path, source: str = "generated",
                 visible: bool = True, gdf: gpd.GeoDataFrame | None = None,
                 meta: dict[str, Any] | None = None) -> None:
        self.id, self.name, self.path, self.source, self.visible = id, name, path, source, visible
        self._gdf = gdf
        self.meta = meta or {}
        if gdf is not None and not self.meta:
            self.meta = self._describe(gdf)

    @staticmethod
    def _describe(gdf: gpd.GeoDataFrame) -> dict[str, Any]:
        wgs = gdf if gdf.crs is None or gdf.crs.to_epsg() == 4326 else gdf.to_crs(epsg=4326)
        return {"geometry_type": _geometry_type(gdf), "feature_count": int(len(gdf)),
                "bounds": [float(x) for x in wgs.total_bounds] if not gdf.empty else None}

    @property
    def gdf(self) -> gpd.GeoDataFrame:
        if self._gdf is None:
            gdf = gpd.read_file(self.path)
            self._gdf = gdf if gdf.crs is not None else gdf.set_crs(epsg=4326)
        return self._gdf

    def geometry_type(self) -> str:
        return self.meta["geometry_type"]

    @property
    def feature_count(self) -> int:
        return self.meta["feature_count"]

    def to_descriptor(self) -> dict[str, Any]:
        """Layer metadata for the frontend. The geometry is fetched separately
        from GET /sessions/{id}/layers/{layer_id}/geojson (the file itself)."""
        return {"id": self.id, "name": self.name, "source": self.source, "kind": "geojson",
                "visible": self.visible, **self.meta}

    def index_entry(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "source": self.source,
                "visible": self.visible, **self.meta}


@dataclass
class Session:
    id: str
    layers: dict[str, Layer] = field(default_factory=dict)
    # WMS overlays: only a tile URL, nothing the processing tools can analyse.
    rasters: dict[str, dict[str, Any]] = field(default_factory=dict)
    history: list[dict[str, Any]] = field(default_factory=list)  # LLM message log
    title: str = ""
    created: float = field(default_factory=time.time)
    updated: float = field(default_factory=time.time)

    @property
    def dir(self) -> Path:
        d = settings.workspace_root / self.id
        d.mkdir(parents=True, exist_ok=True)
        return d

    # ---- layers -------------------------------------------------------------

    def add_layer(self, gdf: gpd.GeoDataFrame, name: str, source: str = "generated") -> Layer:
        layer_id = f"layer_{uuid.uuid4().hex[:8]}"
        if gdf.crs is None:
            gdf = gdf.set_crs(epsg=4326)
        layer = Layer(id=layer_id, name=name, path=self.dir / "layers" / f"{layer_id}.geojson",
                      source=source, gdf=gdf)
        write_geojson(gdf, layer.path)
        self.layers[layer_id] = layer
        self.save()
        return layer

    def add_raster(self, descriptor: dict[str, Any]) -> dict[str, Any]:
        descriptor = {**descriptor, "visible": True}
        self.rasters[descriptor["id"]] = descriptor
        self.save()
        return descriptor

    def get_layer(self, layer_id: str) -> Layer:
        if layer_id not in self.layers:
            known = ", ".join(self.layers) or "(none)"
            raise KeyError(f"Unknown layer_id '{layer_id}'. Known layers: {known}")
        return self.layers[layer_id]

    def update_layer(self, layer_id: str, name: str | None = None,
                     visible: bool | None = None) -> None:
        target = self.layers.get(layer_id) or self.rasters.get(layer_id)
        if target is None:
            raise KeyError(f"Unknown layer_id '{layer_id}'")
        if isinstance(target, Layer):
            if name is not None:
                target.name = name
            if visible is not None:
                target.visible = visible
        else:
            if name is not None:
                target["name"] = name
            if visible is not None:
                target["visible"] = visible
        self.save()

    def delete_layer(self, layer_id: str) -> None:
        if self.layers.pop(layer_id, None) is None and self.rasters.pop(layer_id, None) is None:
            raise KeyError(f"Unknown layer_id '{layer_id}'")
        (self.dir / "layers" / f"{layer_id}.geojson").unlink(missing_ok=True)
        self.save()

    def layer_file(self, layer_id: str) -> Path:
        return self.get_layer(layer_id).path

    def layer_descriptors(self) -> list[dict[str, Any]]:
        return [l.to_descriptor() for l in self.layers.values()] + list(self.rasters.values())

    def layer_catalog(self) -> str:
        """Short human/LLM-readable summary of available layers."""
        if not self.layers and not self.rasters:
            return "(no layers yet)"
        lines = [
            f"- {lid}: '{l.name}' ({l.geometry_type()}, {l.feature_count} features, source={l.source})"
            for lid, l in self.layers.items()
        ]
        lines += [f"- {rid}: '{r['name']}' (WMS raster overlay, display only)"
                  for rid, r in self.rasters.items()]
        return "\n".join(lines)

    # ---- persistence --------------------------------------------------------

    def save(self, touch: bool = True) -> None:
        """Write meta, history and layer index (layer data is written on add).
        touch=False keeps `updated`, so housekeeping doesn't reorder the chat list."""
        if touch:
            self.updated = time.time()
        if not self.title:
            first = next((m["content"] for m in self.history if m["role"] == "user"
                          and not str(m["content"]).startswith("[system]")), "")
            first = " ".join(str(first).split())
            self.title = first[:TITLE_MAX] + ("…" if len(first) > TITLE_MAX else "")
        _write_json(self.dir / "meta.json", self.meta())
        _write_json(self.dir / "history.json", self.history)
        index = [l.index_entry() for l in self.layers.values()]
        _write_json(self.dir / "layers" / "index.json",
                    {"vector": index, "rasters": list(self.rasters.values())})

    def meta(self) -> dict[str, Any]:
        return {"id": self.id, "title": self.title or "Neuer Chat",
                "created": self.created, "updated": self.updated}

    @classmethod
    def load(cls, session_id: str) -> "Session":
        d = settings.workspace_root / session_id
        meta = _read_json(d / "meta.json", {})
        session = cls(id=session_id, history=_read_json(d / "history.json", []),
                      title=meta.get("title", ""),
                      created=meta.get("created", d.stat().st_mtime),
                      updated=meta.get("updated", d.stat().st_mtime))
        if session.title == "Neuer Chat":
            session.title = ""
        index = _read_json(d / "layers" / "index.json", {})
        migrated = False
        for entry in index.get("vector", []):
            path = d / "layers" / f"{entry['id']}.geojson"
            if not path.exists():
                continue
            meta = {k: entry[k] for k in ("geometry_type", "feature_count", "bounds") if k in entry}
            layer = Layer(id=entry["id"], name=entry["name"], path=path,
                          source=entry.get("source", "generated"),
                          visible=entry.get("visible", True), meta=meta)
            if len(meta) < 3:  # saved before metadata existed: describe + compact once
                layer.meta = Layer._describe(layer.gdf)
                write_geojson(layer.gdf, path)
                migrated = True
            session.layers[entry["id"]] = layer
        for raster in index.get("rasters", []):
            session.rasters[raster["id"]] = raster
        if migrated:
            session.save(touch=False)
        if not session.title:  # sessions from before persistence: title from first trace
            for event in next(iter(session.turns()), []):
                if event.get("type") == "user":
                    session.title = str(event.get("content", ""))[:TITLE_MAX]
                    break
        return session

    # ---- traces (one event log per turn, also what the chat view replays) ----

    def new_trace_path(self) -> Path:
        traces = self.dir / "traces"
        traces.mkdir(exist_ok=True)
        return traces / f"trace_{time.time_ns() // 1_000_000}.json"

    def write_trace(self, events: list[dict[str, Any]], path: Path) -> Path:
        _write_json(path, events)
        return path

    def turns(self) -> list[list[dict[str, Any]]]:
        traces = settings.workspace_root / self.id / "traces"
        if not traces.is_dir():
            return []
        files = sorted(traces.glob("trace_*.json"), key=_trace_sort_key)
        return [[strip_geometry(e) for e in _read_json(f, [])] for f in files]


class SessionStore:
    """Sessions live in memory while used and are loaded from disk on demand."""

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    def create(self) -> Session:
        sid = f"sess_{uuid.uuid4().hex[:12]}"
        session = Session(id=sid)  # nothing is written until the first message/upload
        self._sessions[sid] = session
        return session

    def _exists_on_disk(self, session_id: str) -> bool:
        return bool(_SESSION_ID.match(session_id)) and (settings.workspace_root / session_id).is_dir()

    def get(self, session_id: str) -> Session:
        if session_id in self._sessions:
            return self._sessions[session_id]
        if not self._exists_on_disk(session_id):
            raise KeyError(f"Unknown session '{session_id}'")
        session = Session.load(session_id)
        self._sessions[session_id] = session
        return session

    def list(self) -> list[dict[str, Any]]:
        """All saved sessions with at least one turn, newest first."""
        out = []
        for d in settings.workspace_root.glob("sess_*"):
            if not self._exists_on_disk(d.name):
                continue
            meta = _read_json(d / "meta.json", None)
            if meta is None:  # created before persistence: only listed if it has traces
                traces = sorted((d / "traces").glob("trace_*.json"), key=_trace_sort_key) \
                    if (d / "traces").is_dir() else []
                if not traces:
                    continue
                first = next((e for e in _read_json(traces[0], []) if e.get("type") == "user"), {})
                meta = {"id": d.name, "title": str(first.get("content", "Alter Chat"))[:TITLE_MAX],
                        "created": traces[0].stat().st_mtime,
                        "updated": traces[-1].stat().st_mtime}
            out.append(meta)
        return sorted(out, key=lambda m: m["updated"], reverse=True)

    def rename(self, session_id: str, title: str) -> None:
        session = self.get(session_id)
        session.title = title.strip()[:TITLE_MAX * 2]
        session.save()

    def delete(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)
        if self._exists_on_disk(session_id):
            shutil.rmtree(settings.workspace_root / session_id)


store = SessionStore()
