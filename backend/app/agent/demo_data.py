"""Plausible, clearly labelled demo features for the mock agent. No external calls.

Every feature carries `source: "Demo data"` and `demo: true`. Output is deterministic for a given seed, and
the feature count is capped so huge areas stay cheap.
"""

import hashlib
import math
import random
from collections.abc import Callable
from typing import Any

from shapely import affinity
from shapely.geometry import Point, box, mapping
from shapely.geometry.base import BaseGeometry
from shapely.prepared import prep

from app.agent.geo import area_m2, local_metric, reproject

MAX_FEATURES = 12
DEMO_SOURCE = "Demo data"

PropertyFactory = Callable[[int, random.Random], dict[str, Any]]


def seed_for(text: str, geom: BaseGeometry) -> int:
    """Stable seed from the question and the area, so the same question gives the same demo answer."""
    digest = hashlib.sha256(text.strip().lower().encode() + geom.wkb).digest()
    return int.from_bytes(digest[:8], "big")


def _sample_points(geom: BaseGeometry, n: int, rng: random.Random) -> list[Point]:
    """Rejection sampling inside the geometry's bounding box, with a bounded number of attempts."""
    prepared = prep(geom)
    min_x, min_y, max_x, max_y = geom.bounds
    points: list[Point] = []
    attempts = 0
    while len(points) < n and attempts < n * 60:
        attempts += 1
        point = Point(rng.uniform(min_x, max_x), rng.uniform(min_y, max_y))
        if prepared.contains(point):
            points.append(point)
    if not points and n > 0:
        points.append(geom.representative_point())
    return points


def _feature(geom: BaseGeometry, properties: dict[str, Any]) -> dict[str, Any]:
    return {"type": "Feature", "geometry": mapping(geom), "properties": properties}


def _base_properties(index: int, id_prefix: str, name: str) -> dict[str, Any]:
    return {
        "id": f"{id_prefix}-{index + 1}",
        "name": f"{name} {index + 1}",
        "source": DEMO_SOURCE,
        "demo": True,
    }


def demo_points(
    geom: BaseGeometry,
    n: int,
    seed: int,
    *,
    id_prefix: str,
    name: str,
    properties: PropertyFactory | None = None,
) -> dict[str, Any]:
    rng = random.Random(seed)
    features = []
    for index, point in enumerate(_sample_points(geom, max(0, min(n, MAX_FEATURES)), rng)):
        props = _base_properties(index, id_prefix, name)
        if properties:
            props.update(properties(index, rng))
        features.append(_feature(point, props))
    return {"type": "FeatureCollection", "features": features}


def demo_polygons(
    geom: BaseGeometry,
    n: int,
    seed: int,
    *,
    id_prefix: str,
    name: str,
    properties: PropertyFactory | None = None,
) -> dict[str, Any]:
    """Small rotated rectangles (parks, parking lots, ...) inside the area, sized relative to it."""
    rng = random.Random(seed)
    to_metric, to_wgs84 = local_metric(geom)
    geom_m = reproject(geom, to_metric)
    side = min(600.0, max(20.0, math.sqrt(geom_m.area) / 10))
    features = []
    for center in _sample_points(geom_m, max(0, min(n, MAX_FEATURES)), rng):
        width, height = side * rng.uniform(0.6, 1.4), side * rng.uniform(0.5, 1.2)
        rect = box(center.x - width / 2, center.y - height / 2, center.x + width / 2, center.y + height / 2)
        rect = affinity.rotate(rect, rng.uniform(-35, 35), origin=center)
        clipped_m = rect.intersection(geom_m)
        if clipped_m.is_empty or clipped_m.area < 1:
            continue
        # Clip again in WGS84: straight edges differ slightly between the two projections.
        polygon = reproject(clipped_m, to_wgs84).intersection(geom)
        if polygon.is_empty:
            continue
        props = _base_properties(len(features), id_prefix, name)
        props["area_m2"] = round(area_m2(polygon))
        if properties:
            props.update(properties(len(features), rng))
        features.append(_feature(polygon, props))
    return {"type": "FeatureCollection", "features": features}
