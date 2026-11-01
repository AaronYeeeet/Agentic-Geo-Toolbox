import math
import time

import pytest
from pyproj import Transformer
from shapely.geometry import Point, box, mapping, shape

from app.agent.demo_data import MAX_FEATURES, demo_points, demo_polygons, seed_for
from app.agent.geo import area_m2, feature_collection_bbox, reproject, resolve_area
from app.protocol.models import ChatContext

# ETRS89 / LAEA Europe: an equal-area projection, so a 1000 m square there is exactly 1 km².
_TO_WGS84 = Transformer.from_crs("EPSG:3035", "EPSG:4326", always_xy=True)
_TO_LAEA = Transformer.from_crs("EPSG:4326", "EPSG:3035", always_xy=True)


def square_km_near_darmstadt():
    x, y = _TO_LAEA.transform(8.6512, 49.8728)
    return reproject(box(x, y, x + 1000, y + 1000), _TO_WGS84)


def selection(geometry, kind="polygon"):
    return ChatContext.model_validate(
        {"selection": {"type": "Feature", "geometry": mapping(geometry), "properties": {"kind": kind}}}
    )


GERMANY = box(5.87, 47.27, 15.04, 55.06)
BOWTIE = shape(
    {
        "type": "Polygon",
        "coordinates": [[[8.64, 49.86], [8.66, 49.88], [8.66, 49.86], [8.64, 49.88], [8.64, 49.86]]],
    }
)


def test_area_of_a_one_km_square_is_one_million_m2():
    assert area_m2(square_km_near_darmstadt()) == pytest.approx(1_000_000, rel=0.005)


def test_resolve_area_prefers_the_selection():
    square = square_km_near_darmstadt()

    area = resolve_area(selection(square))

    assert area.source == "selection"
    assert area.area_m2 == pytest.approx(1_000_000, rel=0.005)


def test_resolve_area_falls_back_to_the_viewport():
    context = ChatContext.model_validate(
        {"viewport": {"bbox": [8.64, 49.86, 8.66, 49.88], "center": [8.65, 49.87], "zoom": 15}}
    )

    area = resolve_area(context)

    assert area.source == "viewport"
    assert box(8.64, 49.86, 8.66, 49.88).covers(area.geometry)


def test_resolve_area_without_selection_or_viewport_uses_the_default_area():
    area = resolve_area(ChatContext())

    assert area.source == "default"
    assert area.area_m2 > 0


def test_point_selection_becomes_a_300_m_buffer():
    area = resolve_area(selection(Point(8.6512, 49.8728), kind="feature"))

    assert area.source == "selection"
    assert area.area_m2 == pytest.approx(math.pi * 300**2, rel=0.02)


def test_selection_with_empty_coordinates_falls_back_to_the_viewport():
    context = ChatContext.model_validate(
        {
            "viewport": {"bbox": [8.64, 49.86, 8.66, 49.88], "center": [8.65, 49.87], "zoom": 15},
            "selection": {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": []}},
        }
    )

    assert resolve_area(context).source == "viewport"


def test_demo_points_lie_inside_the_area_and_are_labelled():
    square = square_km_near_darmstadt()

    collection = demo_points(square, 8, seed=42, id_prefix="school", name="Demo school")

    assert len(collection["features"]) == 8
    for feature in collection["features"]:
        assert square.covers(shape(feature["geometry"]))
        props = feature["properties"]
        assert props["id"].startswith("school-")
        assert props["name"].startswith("Demo school")
        assert props["source"] == "Demo data"
        assert props["demo"] is True


def test_demo_polygons_lie_inside_the_area():
    square = square_km_near_darmstadt()

    collection = demo_polygons(square, 5, seed=7, id_prefix="green", name="Green space")

    assert 1 <= len(collection["features"]) <= 5
    for feature in collection["features"]:
        assert square.buffer(1e-9).covers(shape(feature["geometry"]))
        assert feature["properties"]["area_m2"] > 0


def test_same_seed_gives_the_same_features():
    square = square_km_near_darmstadt()

    first = demo_points(square, 6, seed=seed_for("schools", square), id_prefix="s", name="S")
    second = demo_points(square, 6, seed=seed_for("schools", square), id_prefix="s", name="S")

    assert first == second


@pytest.mark.parametrize("geometry", [GERMANY, BOWTIE], ids=["germany", "self-intersecting"])
def test_huge_or_invalid_areas_stay_bounded_and_fast(geometry):
    area = resolve_area(selection(geometry))
    start = time.perf_counter()

    points = demo_points(area.geometry, 50, seed=1, id_prefix="p", name="P")
    polygons = demo_polygons(area.geometry, 50, seed=1, id_prefix="g", name="G")

    assert time.perf_counter() - start < 0.2
    assert len(points["features"]) <= MAX_FEATURES
    assert len(polygons["features"]) <= MAX_FEATURES
    assert area.area_m2 > 0


def test_feature_collection_bbox():
    collection = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "geometry": mapping(Point(8.64, 49.86)), "properties": {}},
            {"type": "Feature", "geometry": mapping(Point(8.66, 49.88)), "properties": {}},
        ],
    }

    assert feature_collection_bbox(collection) == pytest.approx((8.64, 49.86, 8.66, 49.88))
