"""OpenStreetMap data retrieval via osmnx (Overpass API under the hood)."""
from __future__ import annotations

import threading
import time

import osmnx as ox
import osmnx._overpass as _overpass
import requests
from osmnx._errors import ResponseStatusCodeError

from ...config import settings
from ...workspace import Session
from ..registry import ToolResult, tool

# Cache Overpass/Nominatim responses: repeated queries return instantly and
# runs become reproducible even if OSM data changes in the meantime.
ox.settings.use_cache = True
ox.settings.cache_folder = str(settings.workspace_root / "osm_cache")
ox.settings.requests_timeout = 90  # per HTTP call (osmnx default: 180 s)

# The public Overpass server is often overloaded (HTTP 502/504); fall back to mirrors.
_OVERPASS_URLS = [
    "https://overpass-api.de/api",
    "https://overpass.kumi.systems/api",
    "https://overpass.private.coffee/api",
]
_SERVER_DEADLINE_S = 120  # give up on a server after this, then try the next one

# osmnx retries HTTP 429/504 ("server busy") by calling _overpass_request
# recursively, with no upper bound, so a request to an overloaded server can
# hang forever. Wrapping that function lets every retry check a deadline first.
_deadline = threading.local()
_original_overpass_request = _overpass._overpass_request


def _overpass_request_with_deadline(data):
    end = getattr(_deadline, "end", None)
    if end is not None and time.monotonic() > end:
        raise TimeoutError(f"no answer within {_SERVER_DEADLINE_S}s (server busy)")
    return _original_overpass_request(data)


_overpass._overpass_request = _overpass_request_with_deadline

_TAGS_DESC = (
    "OSM tag filter as an object. Values may be true (any value), a string, or a "
    'list of strings. Examples: {"building": true}, {"amenity": "school"}, '
    '{"leisure": ["park", "garden"]}, {"landuse": "forest"}.'
)


def _fetch(place: str | None, bbox: list[float] | None, tags: dict):
    if place:
        return ox.features_from_place(place, tags)
    if bbox and len(bbox) == 4:
        # bbox given as [south, west, north, east]
        south, west, north, east = bbox
        # osmnx v2 expects bbox=(left, bottom, right, top) = (west, south, east, north)
        return ox.features_from_bbox(bbox=(west, south, east, north), tags=tags)
    raise ValueError("Provide either 'place' (a place name) or 'bbox' [south, west, north, east].")


def _fetch_with_fallback(place: str | None, bbox: list[float] | None, tags: dict):
    errors = []
    for url in _OVERPASS_URLS:
        ox.settings.overpass_url = url
        # Only the main server has a parseable /status page; on mirrors osmnx
        # would otherwise sleep a flat 60 s before every request.
        ox.settings.overpass_rate_limit = url == _OVERPASS_URLS[0]
        _deadline.end = time.monotonic() + _SERVER_DEADLINE_S
        try:
            return _fetch(place, bbox, tags)
        except (ResponseStatusCodeError, TimeoutError, requests.RequestException) as exc:
            errors.append(f"{url}: {type(exc).__name__}: {str(exc)[:100]}")
        finally:
            _deadline.end = None
    raise RuntimeError(
        "All OpenStreetMap (Overpass) servers are overloaded right now. Suggest the "
        "user retry in a few minutes or use a smaller area (bbox). Details: "
        + " | ".join(errors)
    )


@tool(
    name="fetch_osm",
    description="Fetch features from OpenStreetMap for a place name or bounding "
    "box, filtered by OSM tags. Returns them as a new map layer. Good for "
    "buildings, roads, amenities, land use, water, parks, etc.",
    parameters={
        "type": "object",
        "properties": {
            "tags": {"type": "object", "description": _TAGS_DESC},
            "place": {
                "type": "string",
                "description": "Place name to geocode, e.g. 'Darmstadt, Germany'. "
                "Use this OR bbox.",
            },
            "bbox": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Bounding box [south, west, north, east] in WGS84. Use this OR place.",
            },
            "name": {"type": "string", "description": "Human-readable name for the resulting layer."},
        },
        "required": ["tags"],
    },
)
def fetch_osm(session: Session, tags: dict, place: str | None = None,
              bbox: list[float] | None = None, name: str | None = None) -> ToolResult:
    gdf = _fetch_with_fallback(place, bbox, tags)
    if gdf is None or gdf.empty:
        return ToolResult(summary=f"No OSM features found for tags={tags}.")

    gdf = gdf.reset_index()
    # Drop osmnx's list-valued member columns (node/way ids): useless on the map
    # and they bloat the GeoJSON sent to the browser.
    gdf = gdf.drop(columns=[c for c in ("nodes", "ways") if c in gdf.columns])

    layer_name = name or f"OSM {tags}"
    layer = session.add_layer(gdf.to_crs(epsg=4326), layer_name, source="osm")
    where = place or f"bbox {bbox}"
    return ToolResult(
        summary=(f"Fetched {len(gdf)} OSM features ({layer.geometry_type()}) for {where} "
                 f"with tags {tags}. Stored as layer '{layer.id}'."),
        layers=[layer.to_descriptor()],
    )
