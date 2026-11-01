"""Geometry helpers for the agent: geodesic areas, metric buffers and the area a question refers to."""

from dataclasses import dataclass
from typing import Any, Literal

import shapely
from pyproj import CRS, Geod, Transformer
from shapely import make_valid
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon, box, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from app.protocol.models import BBox, ChatContext

GEOD = Geod(ellps="WGS84")

# Fallback area when the request has neither a selection nor a viewport: around Fraunhofer IGD, Darmstadt.
DEFAULT_BBOX: BBox = (8.645, 49.870, 8.665, 49.882)
# Demo features stay away from the viewport edges, where floating panels cover the map.
VIEWPORT_INSET = 0.12
POINT_BUFFER_M = 300
LINE_BUFFER_M = 50

AreaSource = Literal["selection", "viewport", "default"]


@dataclass(frozen=True)
class ResolvedArea:
    """The area a question refers to, as a WGS84 Polygon or MultiPolygon."""

    geometry: BaseGeometry
    source: AreaSource
    area_m2: float
    kind: str | None = None


def area_m2(geom: BaseGeometry) -> float:
    """Geodesic area on the WGS84 ellipsoid, in square metres."""
    area, _perimeter = GEOD.geometry_area_perimeter(geom)
    return abs(area)


def local_metric(geom: BaseGeometry) -> tuple[Transformer, Transformer]:
    """Transformers to and from an azimuthal equidistant projection centred on the geometry (metres)."""
    centre = geom.centroid
    aeqd = CRS.from_proj4(f"+proj=aeqd +lat_0={centre.y} +lon_0={centre.x} +datum=WGS84 +units=m +no_defs")
    to_metric = Transformer.from_crs("EPSG:4326", aeqd, always_xy=True)
    to_wgs84 = Transformer.from_crs(aeqd, "EPSG:4326", always_xy=True)
    return to_metric, to_wgs84


def reproject(geom: BaseGeometry, transformer: Transformer) -> BaseGeometry:
    return shapely.transform(geom, transformer.transform, interleaved=False)


def buffer_m(geom: BaseGeometry, meters: float) -> BaseGeometry:
    to_metric, to_wgs84 = local_metric(geom)
    return reproject(reproject(geom, to_metric).buffer(meters), to_wgs84)


def _polygonal(geom: BaseGeometry) -> BaseGeometry | None:
    if not geom.is_valid:
        geom = make_valid(geom)
    if isinstance(geom, Polygon | MultiPolygon):
        return None if geom.is_empty else geom
    if isinstance(geom, GeometryCollection):
        parts = [g for g in geom.geoms if isinstance(g, Polygon | MultiPolygon) and not g.is_empty]
        return unary_union(parts) if parts else None
    return None


def _selection_area(context: ChatContext) -> tuple[BaseGeometry, str | None] | None:
    selection = context.selection
    if selection is None:
        return None
    try:
        geom = shape(selection.geometry)
    except (ValueError, TypeError, KeyError, IndexError, AttributeError):
        return None
    if geom.is_empty:
        return None
    kind = selection.properties.get("kind")
    if geom.geom_type in ("Point", "MultiPoint"):
        return buffer_m(geom, POINT_BUFFER_M), kind
    if geom.geom_type in ("LineString", "MultiLineString"):
        return buffer_m(geom, LINE_BUFFER_M), kind
    polygon = _polygonal(geom)
    return (polygon, kind) if polygon is not None else None


def resolve_area(context: ChatContext) -> ResolvedArea:
    """The selection if there is a usable one, else the (inset) viewport, else a default area."""
    selected = _selection_area(context)
    if selected is not None:
        geom, kind = selected
        return ResolvedArea(geom, "selection", area_m2(geom), kind)
    if context.viewport is not None:
        west, south, east, north = context.viewport.bbox
        dx, dy = (east - west) * VIEWPORT_INSET, (north - south) * VIEWPORT_INSET
        geom = box(west + dx, south + dy, east - dx, north - dy)
        return ResolvedArea(geom, "viewport", area_m2(geom), "view")
    geom = box(*DEFAULT_BBOX)
    return ResolvedArea(geom, "default", area_m2(geom), None)


def feature_collection_bbox(collection: dict[str, Any]) -> BBox:
    bounds = [shape(f["geometry"]).bounds for f in collection.get("features", []) if f.get("geometry")]
    if not bounds:
        raise ValueError("feature collection has no geometries")
    return (
        min(b[0] for b in bounds),
        min(b[1] for b in bounds),
        max(b[2] for b in bounds),
        max(b[3] for b in bounds),
    )
