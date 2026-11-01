"""Smoke test: run every tool directly, WITHOUT the LLM (no API key needed).

Shows which parts of the pipeline work on this machine / network and how long
each tool takes. Run from the backend folder:

    python -m scripts.smoke_test            # full run (OSM + online services)
    python -m scripts.smoke_test --offline  # only local geoprocessing on a tiny test layer
"""
from __future__ import annotations

import sys
import time

import geopandas as gpd
from shapely.geometry import Point

from app.agent import tools  # noqa: F401  (importing tools registers them)
from app.agent.registry import get_tool
from app.workspace import store

session = store.create()
failures = 0


def run(tool_name: str, **kwargs):
    global failures
    start = time.time()
    try:
        result = get_tool(tool_name).func(session, **kwargs)
    except Exception as exc:
        failures += 1
        print(f"FAIL {tool_name:<22} {time.time() - start:5.1f}s  {type(exc).__name__}: {str(exc)[:160]}")
        return None
    summary = result.summary.replace("\n", " | ")
    print(f"ok   {tool_name:<22} {time.time() - start:5.1f}s  {summary[:160]}")
    return result


def last_layer_id() -> str:
    return list(session.layers)[-1]


def main(offline: bool) -> None:
    if offline:
        # Three points in Darmstadt city centre as a stand-in for real data.
        pts = gpd.GeoDataFrame(
            {"name": ["Luisenplatz", "Schloss", "Hbf"]},
            geometry=[Point(8.6512, 49.8728), Point(8.6563, 49.8725), Point(8.6299, 49.8725)],
            crs="EPSG:4326",
        )
        points = session.add_layer(pts, "test points", source="test").id
    else:
        run("fetch_osm", bbox=[49.868, 8.645, 49.878, 8.660], tags={"amenity": "school"},
            name="Schulen Innenstadt")
        points = last_layer_id() if session.layers else None
        if points is None:
            print("OSM unavailable, nothing to process.")
            return

    run("buffer", layer_id=points, distance_m=300)
    buf = last_layer_id()
    run("buffer", layer_id=points, distance_m=300, dissolve=True)
    dissolved = last_layer_id()
    run("layer_stats", layer_id=buf)
    run("layer_stats", layer_id=dissolved)
    run("centroids", layer_id=buf)
    run("clip", layer_id=points, mask_layer_id=dissolved)
    run("intersection", layer_a=buf, layer_b=dissolved)
    run("classify_surface", layer_id=dissolved)
    run("list_layers")

    if not offline:
        run("search_open_data", query="Radwege")
        run("wms_capabilities",
            url="https://www.gds-srv.hessen.de/cgi-bin/lika-services/ogc-free-images.ows")
        run("add_wms_layer",
            url="https://www.gds-srv.hessen.de/cgi-bin/lika-services/ogc-free-images.ows",
            layers="he_dop20_rgb", name="Luftbild Hessen")

    print(f"\n{failures} failure(s).")


if __name__ == "__main__":
    main(offline="--offline" in sys.argv)
    sys.exit(1 if failures else 0)
