"""
Klima-Fragen (Stufe 1, grobe Abschätzung) - Methode und Grenzen: docs/starkregen-hitze.md

  starkregen(lat, lon, ...) -> "Was passiert bei Starkregen, wenn wir hier pflastern?"
                               Fließwege, Senken, in denen sich Wasser sammelt, Wirkung der Versiegelung
  hitze(lat, lon, ...)      -> "Wird es wärmer, wenn wir Bäume fällen oder Flächen versiegeln?"
                               Temperaturänderung in der Umgebung, Oberflächen, Schatten

Daten: Flächen/Gebäude/Bäume aus OSM (lokal, sonst Overpass mit kurzem Timeout),
Höhenmodell aus den freien AWS Terrain Tiles (EU-DEM/SRTM, ca. 25-30 m, in output/cache/terrain).
"""
import hashlib
import heapq
import json
import math
import os
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import shapely
from PIL import Image
from shapely.geometry import LineString, Point, Polygon, mapping

import geo_tools
import local_osm
from impact_tools import KIND_DE, TO_UTM, TO_WGS, _out, _write_geojson

TERRAIN_URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
TERRAIN_Z = 14   # ca. 6 m Pixel; die Quelldaten (EU-DEM/SRTM) sind aber nur ca. 25-30 m genau
TERRAIN_CACHE = os.path.join(geo_tools.CACHE_DIR, "terrain")
ONLINE_TIMEOUT = 12  # Sekunden: lieber schnell auf lokale Daten ausweichen als lange warten

# Bodenbedeckung: Name, Versiegelung (0..1), Abflussbeiwert bei Starkregen, Oberfläche an Sommernachmittag (°C)
COVER = {
    0: ("unbekannt", 0.35, 0.45, 38),
    1: ("Wohngebiet (Gärten/Höfe)", 0.45, 0.50, 38),
    2: ("Gewerbe/Industrie", 0.80, 0.75, 45),
    3: ("Grünfläche/Rasen", 0.0, 0.25, 33),
    4: ("Acker/Wiese", 0.0, 0.30, 35),
    5: ("Wald", 0.0, 0.10, 27),
    6: ("Wasser", 0.0, 1.00, 25),
    7: ("Pflaster/Platz/Parkplatz", 0.90, 0.75, 45),
    8: ("Asphalt (Straße)", 1.0, 0.90, 52),
    9: ("Gebäude", 1.0, 0.90, 45),
}
SEAL = np.array([COVER[k][1] for k in range(10)])
RUNOFF = np.array([COVER[k][2] for k in range(10)])
TSURF = np.array([COVER[k][3] for k in range(10)], dtype=float)
T_SHADE = 29.0                 # Boden im Baumschatten
PRIO = {0: 0, 1: 0, 2: 0, 4: 1, 3: 2, 5: 3, 6: 4, 7: 5, 8: 6, 9: 8}  # spätere überschreiben frühere
PRIO_LINE = 7                  # Straßen über Flächen, aber unter Gebäuden

UNSEALED = {"grass", "gravel", "fine_gravel", "dirt", "ground", "earth", "sand", "compacted", "unpaved",
            "woodchips", "mud", "pebblestone", "grass_paver", "rock", "wood"}
PAVERS = {"paving_stones", "sett", "cobblestone", "unhewn_cobblestone", "concrete:plates", "bricks"}
ROAD_WIDTH = {"motorway": 25, "trunk": 16, "primary": 12, "secondary": 10, "tertiary": 8, "unclassified": 6,
              "residential": 6, "living_street": 5, "service": 4, "pedestrian": 6, "busway": 7, "track": 3,
              "footway": 2, "cycleway": 2, "path": 1.5, "steps": 2, "bridleway": 2}
GREEN_LANDUSE = {"grass", "village_green", "recreation_ground", "cemetery", "flowerbed", "greenfield"}
FARM_LANDUSE = {"farmland", "meadow", "orchard", "vineyard", "allotments", "plant_nursery"}
GRAY_LANDUSE = {"commercial", "retail", "industrial", "railway", "construction", "garages", "brownfield"}

# Hitze: grobe Literaturwerte (Sommernachmittag, Lufttemperatur), Spanne niedrig/mittel/hoch.
# Änderung um 100 %-Punkte Versiegelung bzw. Baumkronen in der Nachbarschaft (Gauß, Sigma 50 m)
AIR_IMPERV_K = (1.0, 2.0, 3.0)
AIR_CANOPY_K = (2.0, 3.0, 5.0)
NEIGHBOUR_SIGMA_M = 50
SENSITIVE = '"amenity"~"^(school|kindergarten|childcare|hospital|clinic|nursing_home|social_facility)$"'

MASSNAHMEN = {
    "versiegeln": "Fläche wird gepflastert (Bäume entfallen)",
    "asphaltieren": "Fläche wird asphaltiert (Bäume entfallen)",
    "baeume_faellen": "Bäume werden gefällt, Boden bleibt",
    "entsiegeln": "versiegelte Fläche wird zu Grünfläche",
    "baeume_pflanzen": "Bäume werden gepflanzt (ca. 60 % Kronendeckung)",
}


# ---------- Raster-Grundlagen ----------
def _grid(lat, lon, half, cell):
    x0, y0 = TO_UTM.transform(lon, lat)
    n = int(round(2 * half / cell))
    left, top = x0 - half, y0 + half
    lons, lats = TO_WGS.transform([left, left + 2 * half, left, left + 2 * half], [top, top, top - 2 * half, top - 2 * half])
    return {"x0": x0, "y0": y0, "n": n, "cell": cell, "left": left, "top": top,
            "xc": left + (np.arange(n) + 0.5) * cell, "yc": top - (np.arange(n) + 0.5) * cell,
            "bbox": (min(lats), min(lons), max(lats), max(lons))}


def _burn(arr, g, geom, value):
    """Alle Zellen, deren Mittelpunkt in geom liegt, auf value setzen."""
    minx, miny, maxx, maxy = geom.bounds
    cell, left, top, n = g["cell"], g["left"], g["top"], g["n"]
    c0, c1 = max(0, int((minx - left) // cell)), min(n, int((maxx - left) // cell) + 1)
    r0, r1 = max(0, int((top - maxy) // cell)), min(n, int((top - miny) // cell) + 1)
    if c0 >= c1 or r0 >= r1:
        return
    X, Y = np.meshgrid(g["xc"][c0:c1], g["yc"][r0:r1])
    shapely.prepare(geom)
    arr[r0:r1, c0:c1][shapely.contains_xy(geom, X, Y)] = value


def _circle(g, radius):
    X, Y = np.meshgrid(g["xc"], g["yc"])
    return (X - g["x0"]) ** 2 + (Y - g["y0"]) ** 2 <= radius ** 2


def _cells_geom(mask, g):
    r, c = np.nonzero(mask)
    if not len(r):
        return None
    cell, left, top = g["cell"], g["left"], g["top"]
    boxes = shapely.box(left + c * cell, top - (r + 1) * cell, left + (c + 1) * cell, top - r * cell)
    return shapely.union_all(boxes).simplify(cell / 4)


def _wgs(geom):
    return shapely.transform(geom, lambda c: np.column_stack(TO_WGS.transform(c[:, 0], c[:, 1])))


def _feature(geom_utm, props):
    return {"type": "Feature", "geometry": mapping(_wgs(geom_utm)), "properties": props}


# ---------- OSM-Daten ----------
def _utm_coords(pts):
    xs, ys = TO_UTM.transform([p[0] for p in pts], [p[1] for p in pts])
    return list(zip(xs, ys))


def _poly_utm(outer, inners):
    try:
        geom = Polygon(_utm_coords(outer), [_utm_coords(i) for i in inners if len(i) >= 4])
        return geom if geom.is_valid else geom.buffer(0)
    except Exception:
        return None


def _overpass_shapes(bbox):
    """Umrisse online holen (nur Wege, keine Multipolygone), mit Cache und kurzem Timeout."""
    s, w, n, e = bbox
    b = f"({s:.5f},{w:.5f},{n:.5f},{e:.5f})"
    keys = ['"building"', '"landuse"', '"natural"', '"leisure"', '"amenity"="parking"', '"highway"',
            '"area:highway"', '"water"', '"waterway"']
    query = f"[out:json][timeout:25];({''.join(f'way[{k}]{b};' for k in keys)});out tags geom;"
    path = os.path.join(geo_tools.CACHE_DIR, "shapes_" + hashlib.sha1(query.encode()).hexdigest()[:16] + ".json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            osm = json.load(f)
    else:
        osm, _ = geo_tools._overpass(query, timeout=ONLINE_TIMEOUT, rounds=1)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(osm, f)
    polys, lines = [], []
    for el in osm.get("elements", []):
        pts = [(p["lon"], p["lat"]) for p in el.get("geometry", []) if p]
        tags = {k: v for k, v in el.get("tags", {}).items() if k in local_osm.AREA_KEYS}
        if len(pts) < 2:
            continue
        if (tags.get("highway") and tags.get("area") != "yes") or tags.get("natural") == "tree_row":
            lines.append((tags, pts))
        elif len(pts) >= 4 and pts[0] == pts[-1]:
            polys.append((tags, [(pts, [])]))
    return polys, lines


def _centroid_shapes(bbox):
    """Notlösung ohne Umrisse: Gebäude als 12x12-m-Quadrate um den Mittelpunkt, Straßen aus dem lokalen Netz."""
    s, w, n, e = bbox
    polys = []
    for el in local_osm.query('"building"', bbox):
        dlat, dlon = 6 / 111320, 6 / (111320 * math.cos(math.radians(el["lat"])))
        la, lo = el["lat"], el["lon"]
        sq = [(lo - dlon, la - dlat), (lo + dlon, la - dlat), (lo + dlon, la + dlat), (lo - dlon, la + dlat), (lo - dlon, la - dlat)]
        polys.append(({"building": el["tags"].get("building", "yes"), "name": el["tags"].get("name", "")}, [(sq, [])]))
    d = local_osm.load()
    lines = []
    for _, refs, tags in d["drive_ways"]:
        pts = [(d["coords"][r][1], d["coords"][r][0]) for r in refs if r in d["coords"]]
        if any(s <= la <= n and w <= lo <= e for lo, la in pts):
            lines.append((tags, pts))
    return polys, lines


def _osm_shapes(bbox, warnings):
    if local_osm.areas_cover(bbox):
        return (*local_osm.areas(bbox), f"OSM lokal (Geofabrik-Umrisse, Stand {local_osm.stand()})")
    try:
        return (*_overpass_shapes(bbox), "OSM online (Overpass)")
    except Exception as err:
        if local_osm.covers(bbox):
            warnings.append(f"Overpass nicht erreichbar ({str(err)[:80]}); Notlösung: Gebäude nur als Mittelpunkte, "
                            "keine Grünflächen. Besser einmalig 'python local_osm.py areas' ausführen.")
            return (*_centroid_shapes(bbox), "OSM lokal, nur Mittelpunkte (grob)")
        raise RuntimeError(f"Keine OSM-Flächendaten für dieses Gebiet (Overpass überlastet: {err})")


def _points(tag_filter, bbox, warnings):
    """Punkte (lon, lat, tags) - lokal, sonst Overpass mit kurzem Timeout. Fehler -> leere Liste + Warnung."""
    if local_osm.covers(bbox):
        return [(el["lon"], el["lat"], el["tags"]) for el in local_osm.query(tag_filter, bbox)]
    s, w, n, e = bbox
    q = f"[out:json][timeout:25];(node[{tag_filter}]({s},{w},{n},{e});way[{tag_filter}]({s},{w},{n},{e}););out center tags;"
    try:
        osm, _ = geo_tools._overpass(q, timeout=ONLINE_TIMEOUT, rounds=1)
    except Exception as err:
        warnings.append(f"{tag_filter} konnte nicht geladen werden ({str(err)[:60]})")
        return []
    out = []
    for el in osm.get("elements", []):
        lat = el.get("lat", el.get("center", {}).get("lat"))
        lon = el.get("lon", el.get("center", {}).get("lon"))
        if lat is not None:
            out.append((lon, lat, el.get("tags", {})))
    return out


def _poly_class(t):
    if t.get("building") and t["building"] != "no" and t.get("location") != "underground" \
            and not str(t.get("layer", "0")).startswith("-"):
        return 9
    lu, nat, lei, surf = t.get("landuse"), t.get("natural"), t.get("leisure"), t.get("surface")
    if nat == "water" or t.get("water") or t.get("waterway") or lu in ("reservoir", "basin"):
        return 6
    if nat == "wood" or lu == "forest":
        return 5
    if t.get("amenity") == "parking" or t.get("area:highway") or t.get("highway") or t.get("place") == "square":
        if surf in UNSEALED:
            return 3
        return 8 if surf in ("asphalt", "concrete") and (t.get("area:highway") or t.get("highway")) else 7
    if lei in ("pitch", "track", "stadium"):
        return 3 if surf in UNSEALED or not surf else 7
    if lei in ("park", "garden", "playground", "dog_park", "golf_course", "nature_reserve") or lu in GREEN_LANDUSE \
            or nat in ("grassland", "scrub", "heath"):
        return 3
    if lu in FARM_LANDUSE:
        return 4
    if lu == "residential":
        return 1
    if lu in GRAY_LANDUSE:
        return 2
    return None


def _line_class(t):
    hw = t.get("highway")
    if not hw or t.get("tunnel") in ("yes", "building_passage", "culvert"):
        return None, 0
    width = ROAD_WIDTH.get(hw.replace("_link", ""))
    surf = t.get("surface")
    if width is None or surf in UNSEALED or (hw in ("path", "track", "bridleway") and not surf):
        return None, 0
    if surf in PAVERS or (hw in ("footway", "pedestrian", "steps") and surf not in ("asphalt", "concrete")):
        return 7, width
    return 8, width


def _land_cover(g, polys, lines, trees):
    """Bodenbedeckung (Klasse je Zelle), Baumkronen-Anteil, Gebäude und Straßennamen (für Ortsangaben)."""
    n = g["n"]
    cls = np.zeros((n, n), np.int8)
    canopy = np.zeros((n, n), np.float32)
    items, buildings, roads, canopy_geoms = [], [], [], []
    for tags, rings in polys:
        k = _poly_class(tags)
        if k is None:
            continue
        for outer, inners in rings:
            geom = _poly_utm(outer, inners)
            if geom is None or geom.is_empty:
                continue
            items.append((PRIO[k], k, geom))
            if k == 9:
                buildings.append((geom, tags.get("name", ""), tags.get("building", "")))
            if k == 5:
                canopy_geoms.append(geom)
    for tags, pts in lines:
        line = LineString(_utm_coords(pts))
        if tags.get("natural") == "tree_row":
            canopy_geoms.append(line.buffer(4))
            continue
        k, width = _line_class(tags)
        if k:
            items.append((PRIO_LINE, k, line.buffer(width / 2, cap_style="flat")))
        if tags.get("name") and tags.get("highway"):
            roads.append((tags["name"], line))
    for _, k, geom in sorted(items, key=lambda t: t[0]):
        _burn(cls, g, geom, k)
    for lon, lat, tags in trees:
        try:
            r = float(str(tags.get("diameter_crown", "8")).split()[0]) / 2
        except ValueError:
            r = 4
        x, y = TO_UTM.transform(lon, lat)
        canopy_geoms.append(Point(x, y).buffer(min(max(r, 2), 12), 12))
    for geom in canopy_geoms:
        _burn(canopy, g, geom, 1.0)
    return {"cls": cls, "canopy": canopy, "buildings": buildings, "roads": roads}


def _apply(cls, canopy, mask, massnahme):
    """Maßnahme in der Fläche mask umsetzen -> (Klassen, Kronen) nachher."""
    if massnahme not in MASSNAHMEN:
        raise ValueError(f"Unbekannte Maßnahme '{massnahme}'. Erlaubt: {', '.join(MASSNAHMEN)}")
    cls2, can2 = cls.copy(), canopy.copy()
    free = mask & (cls != 9)  # Gebäude bleiben stehen
    if massnahme == "baeume_faellen":
        can2[mask] = 0
        cls2[mask & (cls == 5)] = 3
    elif massnahme in ("versiegeln", "asphaltieren"):
        cls2[free] = 7 if massnahme == "versiegeln" else 8
        can2[mask] = 0
    elif massnahme == "entsiegeln":
        cls2[free & np.isin(cls, (0, 1, 2, 7, 8))] = 3
    elif massnahme == "baeume_pflanzen":
        can2[free] = np.maximum(can2[free], 0.6)
    return cls2, can2


def _namer(roads, g):
    """Nächstgelegene benannte Straße zu einem Punkt (UTM) -> 'bei Xstraße'."""
    if not roads:
        return lambda x, y: ""
    tree = shapely.STRtree([r[1] for r in roads])

    def name(x, y):
        i = tree.nearest(Point(x, y))
        return f"bei {roads[int(i)][0]}"
    return name


# ---------- Höhenmodell ----------
def _tile(z, x, y):
    os.makedirs(TERRAIN_CACHE, exist_ok=True)
    path = os.path.join(TERRAIN_CACHE, f"{z}_{x}_{y}.png")
    if not os.path.exists(path):
        req = urllib.request.Request(TERRAIN_URL.format(z=z, x=x, y=y), headers={"User-Agent": "uni-qgis-prototype"})
        with urllib.request.urlopen(req, timeout=ONLINE_TIMEOUT) as r:
            data = r.read()
        with open(path, "wb") as f:
            f.write(data)
    a = np.asarray(Image.open(path).convert("RGB"), dtype=np.float64)
    return a[..., 0] * 256 + a[..., 1] + a[..., 2] / 256 - 32768


def _dem(g):
    """Geländehöhe je Zelle (bilinear aus den Terrain-Kacheln)."""
    X, Y = np.meshgrid(g["xc"], g["yc"])
    lon, lat = TO_WGS.transform(X, Y)
    size = 2 ** TERRAIN_Z * 256
    px = (lon + 180) / 360 * size - 0.5
    py = (1 - np.arcsinh(np.tan(np.radians(lat))) / np.pi) / 2 * size - 0.5
    tx0, tx1 = int(px.min() // 256), int((px.max() + 1) // 256)
    ty0, ty1 = int(py.min() // 256), int((py.max() + 1) // 256)
    tiles = [(x, y) for x in range(tx0, tx1 + 1) for y in range(ty0, ty1 + 1)]
    try:
        with ThreadPoolExecutor(4) as ex:
            arrays = dict(zip(tiles, ex.map(lambda t: _tile(TERRAIN_Z, *t), tiles)))
    except Exception as err:
        raise RuntimeError(f"Höhenmodell (AWS Terrain Tiles) nicht erreichbar und nicht im Cache: {err}")
    mosaic = np.zeros(((ty1 - ty0 + 1) * 256, (tx1 - tx0 + 1) * 256))
    for (x, y), a in arrays.items():
        mosaic[(y - ty0) * 256:(y - ty0 + 1) * 256, (x - tx0) * 256:(x - tx0 + 1) * 256] = a
    fx, fy = px - tx0 * 256, py - ty0 * 256
    ix = np.clip(np.floor(fx).astype(int), 0, mosaic.shape[1] - 2)
    iy = np.clip(np.floor(fy).astype(int), 0, mosaic.shape[0] - 2)
    wx, wy = np.clip(fx - ix, 0, 1), np.clip(fy - iy, 0, 1)
    return ((1 - wy) * ((1 - wx) * mosaic[iy, ix] + wx * mosaic[iy, ix + 1])
            + wy * ((1 - wx) * mosaic[iy + 1, ix] + wx * mosaic[iy + 1, ix + 1]))


# ---------- Wasser: Fließwege und Senken ----------
def _priority_flood(dem, eps=1e-4):
    """Senken füllen (Priority-Flood). Liefert gefülltes Gelände, Abflussziel je Zelle (parent, -1 = verlässt
    das Gebiet) und eine Reihenfolge von unten nach oben."""
    ny, nx = dem.shape
    z = dem.ravel().astype(float).tolist()
    parent = [-1] * (ny * nx)
    done = bytearray(ny * nx)
    edge = set(range(nx)) | set(range((ny - 1) * nx, ny * nx)) | set(range(0, ny * nx, nx)) | set(range(nx - 1, ny * nx, nx))
    heap = [(z[i], i) for i in edge]
    for i in edge:
        done[i] = 1
    heapq.heapify(heap)
    order = []
    while heap:
        h, i = heapq.heappop(heap)
        order.append(i)
        r, c = divmod(i, nx)
        for dr in (-1, 0, 1):
            rr = r + dr
            if rr < 0 or rr >= ny:
                continue
            for dc in (-1, 0, 1):
                cc = c + dc
                if (dr == 0 and dc == 0) or cc < 0 or cc >= nx:
                    continue
                j = rr * nx + cc
                if done[j]:
                    continue
                done[j] = 1
                parent[j] = i
                if z[j] <= h:
                    z[j] = h + eps
                heapq.heappush(heap, (z[j], j))
    return np.array(z).reshape(ny, nx), parent, order


def _label(mask):
    """Zusammenhängende Flächen (8er-Nachbarschaft) nummerieren, -1 = keine."""
    ny, nx = mask.shape
    lab = np.full(mask.shape, -1, np.int32)
    k = 0
    for r0, c0 in zip(*np.nonzero(mask)):
        if lab[r0, c0] >= 0:
            continue
        stack = [(r0, c0)]
        lab[r0, c0] = k
        while stack:
            r, c = stack.pop()
            for rr in (r - 1, r, r + 1):
                for cc in (c - 1, c, c + 1):
                    if 0 <= rr < ny and 0 <= cc < nx and mask[rr, cc] and lab[rr, cc] < 0:
                        lab[rr, cc] = k
                        stack.append((rr, cc))
        k += 1
    return lab, k


def _route(vol, parent, order, label, capacity):
    """Wasser bergab weitergeben. Senken nehmen bis zu ihrem Fassungsvermögen auf, der Rest läuft über
    (oberliegende Senken zuerst). -> Durchfluss je Zelle, gespeichertes Volumen je Senke, Abfluss aus dem Gebiet."""
    acc = vol.ravel().astype(float).tolist()
    lab = label.ravel().tolist()
    left = capacity.astype(float).tolist()
    out = 0.0
    for i in reversed(order):
        v, k, p = acc[i], lab[i], parent[i]
        if k >= 0 and (p < 0 or lab[p] != k):   # Wasser verlässt hier die Senke
            take = min(v, left[k])
            left[k] -= take
            v -= take
            acc[i] = v
        if p >= 0:
            acc[p] += v
        else:
            out += v
    return np.array(acc).reshape(vol.shape), capacity - np.array(left), out


def _water_depth(dem, filled, label, stored, cell_area):
    """Wasserstand je Senke so bestimmen, dass das gespeicherte Volumen hineinpasst (von unten gefüllt)."""
    depth = np.zeros(dem.shape)
    flat = label.ravel()
    idx = np.argsort(flat, kind="stable")
    bounds = np.searchsorted(flat[idx], np.arange(len(stored) + 1))
    d, f = dem.ravel(), filled.ravel()
    out = depth.ravel()
    for k, vol in enumerate(stored):
        if vol <= 0.01:
            continue
        cells = idx[bounds[k]:bounds[k + 1]]
        dk, fk = d[cells], f[cells]
        lo, hi = dk.min(), fk.max()
        for _ in range(40):
            mid = (lo + hi) / 2
            if np.clip(np.minimum(mid, fk) - dk, 0, None).sum() * cell_area < vol:
                lo = mid
            else:
                hi = mid
        out[cells] = np.clip(np.minimum(lo, fk) - dk, 0, None)
    return depth


def _accumulate(vals, parent, order):
    acc = vals.ravel().astype(float).tolist()
    for i in reversed(order):
        if parent[i] >= 0:
            acc[parent[i]] += acc[i]
    return np.array(acc).reshape(vals.shape)


DEPTH_CLASSES = [(0.1, 0.3, "#9ecae1", "10-30 cm"), (0.3, 0.5, "#4292c6", "30-50 cm"),
                 (0.5, 99, "#08306b", "über 50 cm")]


def starkregen(lat, lon, radius_m=50, massnahme="versiegeln", niederschlag_mm=50, kanal_mm=10,
               gebiet_m=1000, prefix="starkregen"):
    """Starkregen vorher/nachher: Fläche (Kreis radius_m um lat/lon) wird versiegelt/entsiegelt.
    niederschlag_mm: Regen in 1 h (50 mm ~ seltener Starkregen, ca. 100-jährlich in Südhessen),
    kanal_mm: was die Kanalisation von versiegelten Flächen aufnimmt, gebiet_m: halbe Kantenlänge."""
    warnings = []
    gebiet_m = int(round(gebiet_m / 10) * 10)
    g5, g10 = _grid(lat, lon, gebiet_m, 5), _grid(lat, lon, gebiet_m, 10)
    polys, lines, quelle = _osm_shapes(g5["bbox"], warnings)
    lc = _land_cover(g5, polys, lines, [])
    mask5 = _circle(g5, radius_m)
    cls_b = lc["cls"]
    cls_a, _ = _apply(cls_b, lc["canopy"], mask5, massnahme)

    n10 = g10["n"]

    def agg(a):  # 5 m -> 10 m
        return a.reshape(n10, 2, n10, 2).mean(axis=(1, 3))

    area = g10["cell"] ** 2
    dem = _dem(g10)
    filled, parent, order = _priority_flood(dem)
    cap = filled - dem
    label, ncomp = _label(cap > 0.02)
    capacity = np.array([cap[label == k].sum() * area for k in range(ncomp)]) if ncomp else np.zeros(0)

    results = {}
    for key, cls in (("vorher", cls_b), ("nachher", cls_a)):
        runoff_mm = np.clip(agg(RUNOFF[cls]) * niederschlag_mm - kanal_mm * agg(SEAL[cls]), 0, None)
        vol = runoff_mm / 1000 * area
        flow, stored, out = _route(vol, parent, order, label, capacity)
        depth = _water_depth(dem, filled, label, stored, area)
        results[key] = {"vol": vol, "stored": stored, "out": out, "depth": depth}
    b, a = results["vorher"], results["nachher"]
    name_of = _namer(lc["roads"], g10)

    # Fließwege (Einzugsgebiet ab 3 ha) und der Weg des Wassers ab der Maßnahme
    contrib = _accumulate(np.full(dem.shape, area), parent, order)
    nx = n10
    xc, yc = g10["xc"], g10["yc"]

    def seg(i):
        p = parent[i]
        return LineString([(xc[i % nx], yc[i // nx]), (xc[p % nx], yc[p // nx])])

    flow_feats = []
    for lo_ha, hi_ha, width in ((3, 10, 2), (10, 50, 3), (50, 1e9, 5)):
        sel = np.nonzero(((contrib >= lo_ha * 1e4) & (contrib < hi_ha * 1e4)).ravel())[0]
        segs = [seg(i) for i in sel if parent[i] >= 0]
        if segs:
            label_ha = f"Fließweg, Einzugsgebiet {lo_ha}-{hi_ha:g} ha" if hi_ha < 1e9 else f"Hauptfließweg, über {lo_ha} ha"
            flow_feats.append(_feature(shapely.line_merge(shapely.union_all(segs)), {
                "name": label_ha, "_style": {"color": "#2171b5", "weight": width, "opacity": 0.7},
                "_popup": f"<b>{label_ha}</b><br>Hierhin fließt Oberflächenwasser zusammen"}))

    # Weg des Wassers: ab dem Rand der Fläche bergab, endet in der ersten Senke, die nicht überläuft
    site_mask = _circle(g10, max(radius_m, 10)).ravel()
    lab_flat = label.ravel()
    full = a["stored"] >= capacity - 0.5 if ncomp else np.zeros(0, bool)
    path, seen = [], set()
    for i in np.nonzero(site_mask)[0].tolist():
        while i >= 0 and i not in seen:
            seen.add(i)
            k = lab_flat[i]
            if k >= 0 and not full[k] and not site_mask[i]:
                break
            if parent[i] >= 0 and not site_mask[parent[i]]:
                path.append(seg(i))
            i = parent[i]
    site = Point(g10["x0"], g10["y0"])
    massnahme_feats = [_feature(site.buffer(radius_m, 32), {
        "name": "Maßnahme", "_style": {"color": "#000000", "fillColor": "#ff7f00", "fillOpacity": 0.4, "weight": 2},
        "_popup": f"<b>{MASSNAHMEN[massnahme]}</b><br>ca. {round(mask5.sum() * 25)} m²"})]
    if path:
        massnahme_feats.append(_feature(shapely.line_merge(shapely.union_all(path)), {
            "name": "Weg des Wassers ab der Fläche", "_style": {"color": "#e31a1c", "weight": 4, "dashArray": "8 6"},
            "_popup": "<b>Weg des Oberflächenwassers ab der Maßnahme</b> (bergab, bis zur nächsten Senke bzw. aus dem Gebiet)"}))

    # Wassertiefe nachher (Klassen) und zusätzliches Wasser
    water_feats = []
    for lo, hi, color, text in DEPTH_CLASSES:
        geom = _cells_geom((a["depth"] >= lo) & (a["depth"] < hi), g10)
        if geom is not None:
            water_feats.append(_feature(geom, {"name": f"Wasser {text}", "_style": {
                "color": color, "fillColor": color, "fillOpacity": 0.6, "weight": 0},
                "_popup": f"<b>Wassertiefe {text}</b><br>Senke, in der sich Regenwasser sammelt (nach der Maßnahme)"}))
    more = _cells_geom(a["depth"] - b["depth"] >= 0.02, g10)
    more_feats = [_feature(more, {"name": "mehr Wasser", "_style": {
        "color": "#e31a1c", "fillColor": "#e31a1c", "fillOpacity": 0.25, "weight": 2},
        "_popup": "<b>Hier steht durch die Maßnahme mindestens 2 cm mehr Wasser</b>"})] if more is not None else []

    # Senken, die mehr Wasser bekommen
    senken = []
    for k in np.argsort(-(a["stored"] - b["stored"]))[:8] if ncomp else []:
        extra = a["stored"][k] - b["stored"][k]
        if extra < 0.5:
            break
        cells = label == k
        r, c = np.nonzero(cells)
        x, y = xc[c].mean(), yc[r].mean()
        senken.append({
            "ort": name_of(x, y), "entfernung_m": round(math.hypot(x - g10["x0"], y - g10["y0"])),
            "zusaetzliches_wasser_m3": round(extra),
            "max_tiefe_cm": {"vorher": round(100 * b["depth"][cells].max()), "nachher": round(100 * a["depth"][cells].max())},
            "flaeche_ueber_10cm_m2": {"vorher": int((b["depth"][cells] >= 0.1).sum() * area),
                                      "nachher": int((a["depth"][cells] >= 0.1).sum() * area)},
            "laeuft_ueber": bool(a["stored"][k] >= capacity[k] - 0.5)})

    # betroffene Gebäude (Wasser >= 10 cm direkt am Gebäude)
    def wet(depth):
        hits = []
        for geom, name, kind in lc["buildings"]:
            minx, miny, maxx, maxy = geom.bounds
            c0, c1 = max(0, int((minx - g10["left"]) // 10) - 1), min(nx, int((maxx - g10["left"]) // 10) + 2)
            r0, r1 = max(0, int((g10["top"] - maxy) // 10) - 1), min(nx, int((g10["top"] - miny) // 10) + 2)
            if c0 < c1 and r0 < r1 and depth[r0:r1, c0:c1].max() >= 0.1:
                hits.append((geom, name, kind, depth[r0:r1, c0:c1].max()))
        return hits
    wet_b, wet_a = wet(b["depth"]), wet(a["depth"])
    before_ids = {id(h[0]) for h in wet_b}
    bld_feats = []
    for geom, name, kind, d in wet_a:
        new = id(geom) not in before_ids
        bld_feats.append(_feature(geom.centroid, {
            "name": name or "Gebäude", "_style": {"radius": 6, "fillColor": "#e31a1c" if new else "#fd8d3c",
                                                  "color": "#ffffff", "weight": 1},
            "_popup": f"<b>{name or 'Gebäude'}</b> ({kind})<br>bis {round(100 * d)} cm Wasser am Gebäude"
                      + ("<br><b>neu betroffen durch die Maßnahme</b>" if new else "")}))

    # sensible Einrichtungen im Wasser
    einrichtungen = []
    for lon_, lat_, tags in _points(SENSITIVE, g10["bbox"], warnings):
        x, y = TO_UTM.transform(lon_, lat_)
        c, r = int((x - g10["left"]) // 10), int((g10["top"] - y) // 10)
        if 0 <= r < nx and 0 <= c < nx:
            win = (slice(max(r - 2, 0), r + 3), slice(max(c - 2, 0), c + 3))
            if a["depth"][win].max() >= 0.1:
                kind = tags.get("amenity", "")
                einrichtungen.append({"name": tags.get("name") or KIND_DE.get(kind, kind), "art": KIND_DE.get(kind, kind),
                                      "wasser_cm": {"vorher": round(100 * b["depth"][win].max()),
                                                    "nachher": round(100 * a["depth"][win].max())}})

    files = {
        "wasser": _write_geojson(_out(f"{prefix}_wasser.geojson"), water_feats),
        "fliesswege": _write_geojson(_out(f"{prefix}_fliesswege.geojson"), flow_feats),
        "mehr_wasser": _write_geojson(_out(f"{prefix}_mehr_wasser.geojson"), more_feats),
        "massnahme": _write_geojson(_out(f"{prefix}_massnahme.geojson"), massnahme_feats),
        "gebaeude": _write_geojson(_out(f"{prefix}_gebaeude.geojson"), bld_feats),
    }
    in_site = mask5
    before_mix = {COVER[k][0]: round(int((cls_b[in_site] == k).sum()) * 25) for k in np.unique(cls_b[in_site])}
    extra_runoff = float((a["vol"] - b["vol"]).sum())

    def ha(depth, t):
        return round(float((depth >= t).sum() * area) / 1e4, 2)

    return {
        "files": files,
        "massnahme": MASSNAHMEN[massnahme], "flaeche_m2": round(int(in_site.sum()) * 25),
        "flaeche_vorher_m2": before_mix,
        "regen": f"{niederschlag_mm} mm in 1 h, Kanalisation nimmt {kanal_mm} mm von versiegelten Flächen auf",
        "zusaetzlicher_oberflaechenabfluss_m3": round(extra_runoff),
        "abflussbeiwert_flaeche": {"vorher": round(float(RUNOFF[cls_b[in_site]].mean()), 2),
                                   "nachher": round(float(RUNOFF[cls_a[in_site]].mean()), 2)},
        "gebiet_ueberflutet_ha": {
            "ab 10 cm": {"vorher": ha(b["depth"], 0.1), "nachher": ha(a["depth"], 0.1)},
            "ab 30 cm": {"vorher": ha(b["depth"], 0.3), "nachher": ha(a["depth"], 0.3)}},
        "wasser_verlaesst_gebiet_m3": {"vorher": round(b["out"]), "nachher": round(a["out"])},
        "senken_mit_mehr_wasser": senken,
        "gebaeude_mit_wasser_ab_10cm": {"vorher": len(wet_b), "nachher": len(wet_a),
                                        "neu_betroffen": sum(1 for h in wet_a if id(h[0]) not in before_ids)},
        "sensible_einrichtungen_im_wasser": einrichtungen[:10],
        "gelaende_hoehe_m": {"min": round(float(dem.min()), 1), "max": round(float(dem.max()), 1),
                             "an_der_flaeche": round(float(dem[n10 // 2, n10 // 2]), 1)},
        "datenquellen": [quelle, "Höhenmodell: AWS Terrain Tiles (EU-DEM/SRTM, ca. 25-30 m Auflösung)"],
        "warnungen": warnings,
        "hinweis": "Grobe Senken- und Fließweganalyse (GIS-Methode wie in Starkregen-Hinweiskarten), keine "
                   "hydrodynamische Simulation: keine Fließgeschwindigkeit/Zeit, Gebäude sind keine Hindernisse, "
                   "Kanalisation pauschal, Höhenmodell grob (Bordsteine, Unterführungen, Mauern fehlen).",
    }


# ---------- Hitze ----------
def _smooth(a, sigma):
    r = int(3 * sigma)
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2)
    k /= k.sum()
    a = np.apply_along_axis(lambda v: np.convolve(v, k, mode="same"), 0, a)
    return np.apply_along_axis(lambda v: np.convolve(v, k, mode="same"), 1, a)


DT_CLASSES = [(1.0, 99, "#99000d", "über +1 K"), (0.5, 1.0, "#ef3b2c", "+0,5 bis +1 K"),
              (0.25, 0.5, "#fc9272", "+0,25 bis +0,5 K"), (0.1, 0.25, "#fee0d2", "+0,1 bis +0,25 K"),
              (-0.25, -0.1, "#deebf7", "-0,1 bis -0,25 K"), (-0.5, -0.25, "#9ecae1", "-0,25 bis -0,5 K"),
              (-1.0, -0.5, "#4292c6", "-0,5 bis -1 K"), (-99, -1.0, "#08519c", "unter -1 K")]


def hitze(lat, lon, radius_m=50, massnahme="baeume_faellen", gebiet_m=400, prefix="hitze"):
    """Temperaturwirkung einer Maßnahme (Kreis radius_m um lat/lon) an einem heißen Sommernachmittag."""
    warnings = []
    cell = 5
    g = _grid(lat, lon, gebiet_m, cell)
    polys, lines, quelle = _osm_shapes(g["bbox"], warnings)
    trees = _points('"natural"="tree"', g["bbox"], warnings)
    lc = _land_cover(g, polys, lines, trees)
    mask = _circle(g, radius_m)
    cls_b, can_b = lc["cls"], lc["canopy"]
    cls_a, can_a = _apply(cls_b, can_b, mask, massnahme)

    s_imp = _smooth(SEAL[cls_a] - SEAL[cls_b], NEIGHBOUR_SIGMA_M / cell)
    s_can = _smooth(can_a - can_b, NEIGHBOUR_SIGMA_M / cell)
    dts = [ki * s_imp - kc * s_can for ki, kc in zip(AIR_IMPERV_K, AIR_CANOPY_K)]
    dt = dts[1]

    def surf(cls, can):
        return can * T_SHADE + (1 - can) * TSURF[cls]

    near = _circle(g, max(radius_m, 100))
    area = cell ** 2
    x0, y0 = g["x0"], g["y0"]
    gone = [(lo, la) for lo, la, _ in trees
            if math.hypot(*(np.subtract(TO_UTM.transform(lo, la), (x0, y0)))) <= radius_m]
    trees_removed = len(gone) if massnahme in ("baeume_faellen", "versiegeln", "asphaltieren") else 0

    # Karte: Temperaturänderung in Klassen, Maßnahme, gefällte Bäume
    dt_feats = []
    for lo, hi, color, text in DT_CLASSES:
        geom = _cells_geom((dt >= lo) & (dt < hi), g)
        if geom is not None:
            dt_feats.append(_feature(geom, {"name": text, "_style": {
                "color": color, "fillColor": color, "fillOpacity": 0.55, "weight": 0},
                "_popup": f"<b>Lufttemperatur {text}</b><br>Sommernachmittag, grobe Abschätzung"}))
    site_feats = [_feature(Point(x0, y0).buffer(radius_m, 32), {
        "name": "Maßnahme", "_style": {"color": "#000000", "fillOpacity": 0, "weight": 2, "dashArray": "6 4"},
        "_popup": f"<b>{MASSNAHMEN[massnahme]}</b><br>ca. {round(int(mask.sum()) * area)} m²"})]
    if trees_removed:
        for lo, la in gone:
            site_feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [lo, la]}, "properties": {
                "name": "Baum (entfällt)", "_style": {"radius": 5, "fillColor": "#8c510a", "color": "#ffffff", "weight": 1},
                "_popup": "Baum aus OSM, entfällt"}})

    # Gebäude und sensible Einrichtungen in der wärmeren/kühleren Zone
    def dt_at(x, y):
        c, r = int((x - g["left"]) // cell), int((g["top"] - y) // cell)
        return float(dt[r, c]) if 0 <= r < g["n"] and 0 <= c < g["n"] else 0.0

    bld_dt = [dt_at(geom.centroid.x, geom.centroid.y) for geom, _, _ in lc["buildings"]]
    sens, sens_feats = [], []
    for lo, la, tags in _points(SENSITIVE, g["bbox"], warnings):
        x, y = TO_UTM.transform(lo, la)
        d = dt_at(x, y)
        if abs(d) < 0.05:
            continue
        kind = tags.get("amenity", "")
        name = tags.get("name") or KIND_DE.get(kind, kind)
        sens.append({"name": name, "art": KIND_DE.get(kind, kind), "entfernung_m": round(math.hypot(x - x0, y - y0)),
                     "aenderung_k": round(d, 2)})
        sens_feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [lo, la]}, "properties": {
            "name": name, "_style": {"radius": 8, "fillColor": "#6a3d9a", "color": "#ffffff", "weight": 2},
            "_popup": f"<b>{name}</b> ({KIND_DE.get(kind, kind)})<br>Lufttemperatur ca. {d:+.2f} K"}})
    sens.sort(key=lambda s: -abs(s["aenderung_k"]))

    files = {
        "temperatur": _write_geojson(_out(f"{prefix}_temperatur.geojson"), dt_feats),
        "massnahme": _write_geojson(_out(f"{prefix}_massnahme.geojson"), site_feats),
        "einrichtungen": _write_geojson(_out(f"{prefix}_einrichtungen.geojson"), sens_feats),
    }
    peak = [float(d.max()) if abs(d.max()) >= abs(d.min()) else float(d.min()) for d in dts]
    lo_, hi_ = sorted((peak[0], peak[2]))
    return {
        "files": files,
        "massnahme": MASSNAHMEN[massnahme], "flaeche_m2": round(int(mask.sum()) * area),
        "baeume_entfallen": trees_removed,
        "baumkronen_m2": {"vorher": round(float(can_b[mask].sum()) * area), "nachher": round(float(can_a[mask].sum()) * area)},
        "versiegelt_m2": {"vorher": round(float(SEAL[cls_b][mask].sum()) * area),
                          "nachher": round(float(SEAL[cls_a][mask].sum()) * area)},
        "umgebung_100m": {
            "versiegelung_prozent": {"vorher": round(100 * float(SEAL[cls_b][near].mean())),
                                     "nachher": round(100 * float(SEAL[cls_a][near].mean()))},
            "baumkronen_prozent": {"vorher": round(100 * float(can_b[near].mean())),
                                   "nachher": round(100 * float(can_a[near].mean()))}},
        "oberflaeche_sommernachmittag_c": {"vorher": round(float(surf(cls_b, can_b)[mask].mean()), 1),
                                           "nachher": round(float(surf(cls_a, can_a)[mask].mean()), 1)},
        "lufttemperatur_aenderung_k": {"maximal": round(peak[1], 2), "spanne": [round(lo_, 2), round(hi_, 2)],
                                       "flaeche_ab_0_1K_ha": round(float((np.abs(dt) >= 0.1).sum() * area) / 1e4, 2),
                                       "reichweite_0_1K_m": _reach(dt, g)},
        "gefuehlte_temperatur": "Im Baumschatten ist es für Menschen an heißen Tagen gefühlt ca. 10-15 °C kühler "
                                "als in der Sonne auf Asphalt (PET, Literaturwert).",
        "gebaeude_in_zone_ab_0_1K": sum(1 for d in bld_dt if abs(d) >= 0.1),
        "sensible_einrichtungen": sens[:10],
        "datenquellen": [quelle, f"Bäume: {len(trees)} Einzelbäume aus OSM (Krone 8 m, wenn nicht angegeben)"],
        "warnungen": warnings,
        "hinweis": "Grobe Abschätzung mit Literaturwerten (Versiegelung +1..3 K, Baumkronen -2..5 K je 100 % "
                   "in ca. 100 m Umkreis), keine Klimasimulation: kein Wind, keine Gebäudeschatten, keine Nacht. "
                   "Nicht in OSM erfasste Bäume fehlen.",
    }


def _reach(dt, g):
    """Wie weit reicht eine Änderung von mindestens 0,1 K (Meter vom Mittelpunkt)?"""
    r, c = np.nonzero(np.abs(dt) >= 0.1)
    if not len(r):
        return 0
    return round(float(np.hypot(g["xc"][c] - g["x0"], g["yc"][r] - g["y0"]).max()))
