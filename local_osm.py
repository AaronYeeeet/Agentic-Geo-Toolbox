"""
Lokale OSM-Daten als Backup für Overpass (überlastet oft).

Einmalig: Hessen-Datei von Geofabrik nach data/osm/hessen-latest.osm.pbf laden, dann
    python local_osm.py
Das schneidet die Region (Standard: Darmstadt + Umland) aus und speichert sie kompakt
(data/osm/region_*.pkl). Danach beantworten fetch_osm, geocode (Kreuzungen) und das
Straßennetz für traffic_impact Anfragen in dieser Region ohne Internet.

Einstellungen in .env (optional):
    OSM_SOURCE=auto        auto = lokal, wenn die Region das Gebiet abdeckt, sonst online
                           local = nur lokal, online = nur Overpass
    LOCAL_OSM_BBOX=49.78,8.50,49.97,8.80    (süd, west, nord, ost)
"""
import hashlib
import math
import os
import pickle
import re
import time

import networkx as nx
from dotenv import load_dotenv

HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(HERE, ".env"))
PBF = os.environ.get("LOCAL_OSM_PBF", os.path.join(HERE, "data", "osm", "hessen-latest.osm.pbf"))
REGION = tuple(float(v) for v in os.environ.get("LOCAL_OSM_BBOX", "49.78,8.50,49.97,8.80").split(","))
SOURCE = os.environ.get("OSM_SOURCE", "auto").lower()

DRIVE = {"motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link", "secondary",
         "secondary_link", "tertiary", "tertiary_link", "unclassified", "residential", "living_street", "road"}
DROP_KEYS = ("source", "note", "fixme", "FIXME", "description", "check_date", "created_by")

_DATA = None


def _pkl_path():
    key = hashlib.sha1(f"{REGION}".encode()).hexdigest()[:10]
    return os.path.join(os.path.dirname(PBF), f"region_{key}.pkl")


def _in_region(lat, lon):
    s, w, n, e = REGION
    return s <= lat <= n and w <= lon <= e


def available():
    return SOURCE != "online" and (os.path.exists(_pkl_path()) or os.path.exists(PBF))


def covers(bbox):
    """True, wenn das Gebiet (süd, west, nord, ost) komplett in der lokalen Region liegt."""
    s, w, n, e = bbox
    return available() and _in_region(s, w) and _in_region(n, e)


def stand():
    path = _pkl_path() if os.path.exists(_pkl_path()) else PBF
    return time.strftime("%d.%m.%Y", time.localtime(os.path.getmtime(path))) if os.path.exists(path) else "?"


def prepare():
    """Region aus der .pbf-Datei ausschneiden und kompakt speichern (dauert einmalig einige Minuten)."""
    import osmium

    if not os.path.exists(PBF):
        raise FileNotFoundError(f"OSM-Datei fehlt: {PBF} (Download: download.geofabrik.de, Hessen)")
    start = time.time()
    objects, streets, coords, drive_ways = [], {}, {}, []
    # EmptyTagFilter: Objekte ohne Tags gar nicht erst an Python geben (sonst Millionen leere Punkte -> sehr langsam).
    # Die Koordinaten der Wege-Knoten werden trotzdem vorher im schnellen C++-Teil gesammelt.
    for obj in osmium.FileProcessor(PBF).with_locations().with_filter(osmium.filter.EmptyTagFilter()):
        if obj.is_node():
            if len(obj.tags) and obj.location.valid() and _in_region(obj.location.lat, obj.location.lon):
                objects.append((obj.location.lat, obj.location.lon, "node", obj.id,
                                {t.k: t.v for t in obj.tags if not t.k.startswith(DROP_KEYS)}))
        elif obj.is_way():
            if not len(obj.tags):
                continue
            pts = [(n.ref, n.location.lat, n.location.lon) for n in obj.nodes if n.location.valid()]
            if not pts or not any(_in_region(la, lo) for _, la, lo in pts):
                continue
            tags = {t.k: t.v for t in obj.tags if not t.k.startswith(DROP_KEYS)}
            lat = sum(p[1] for p in pts) / len(pts)
            lon = sum(p[2] for p in pts) / len(pts)
            objects.append((lat, lon, "way", obj.id, tags))
            hw = tags.get("highway")
            if hw:
                for ref, la, lo in pts:
                    coords[ref] = (la, lo)
                if tags.get("name"):
                    streets.setdefault(tags["name"], set()).update(p[0] for p in pts)
                if hw in DRIVE and tags.get("access") not in ("no", "private") and tags.get("area") != "yes":
                    keep = {k: tags[k] for k in ("highway", "name", "ref", "oneway", "junction", "maxspeed") if k in tags}
                    drive_ways.append((obj.id, [p[0] for p in pts], keep))
    data = {"region": REGION, "objects": objects, "streets": streets, "coords": coords, "drive_ways": drive_ways}
    with open(_pkl_path(), "wb") as f:
        pickle.dump(data, f, protocol=pickle.HIGHEST_PROTOCOL)
    print(f"Region gespeichert: {len(objects)} Objekte, {len(drive_ways)} befahrbare Wege, "
          f"{time.time() - start:.0f}s -> {_pkl_path()}")
    return data


def load():
    global _DATA
    if _DATA is None:
        path = _pkl_path()
        if os.path.exists(path) and (not os.path.exists(PBF) or os.path.getmtime(path) >= os.path.getmtime(PBF)):
            with open(path, "rb") as f:
                _DATA = pickle.load(f)
        else:
            _DATA = prepare()
    return _DATA


# ---------- Abfragen wie Overpass ----------
_COND = re.compile(r'^\s*(!)?"?([^"=!~]+?)"?\s*(?:(=|!=|~|!~)\s*"?(.*?)"?\s*(,\s*i)?)?\s*$')


def _parse_filter(tag_filter):
    """Overpass-Tagfilter wie '"amenity"="parking"', '"building"', '"amenity"~"^(school|kindergarten)$"',
    auch mehrere: '"amenity"="parking"]["access"!="private"'."""
    conds = []
    for part in re.split(r"\]\s*\[", tag_filter.strip().strip("[]")):
        m = _COND.match(part)
        if not m:
            raise ValueError(f"Filter nicht verstanden: {part}")
        neg, key, op, val, icase = m.groups()
        if neg:
            op = "absent"
        elif op in ("~", "!~"):
            val = re.compile(val, re.I if icase else 0)
        conds.append((key.strip(), op, val))
    return conds


def _match(tags, conds):
    for key, op, val in conds:
        v = tags.get(key)
        if op is None and v is None:
            return False
        if op == "absent" and v is not None:
            return False
        if op == "=" and v != val:
            return False
        if op == "!=" and v == val:
            return False
        if op == "~" and (v is None or not val.search(v)):
            return False
        if op == "!~" and v is not None and val.search(v):
            return False
    return True


def query(tag_filter, bbox):
    """Objekte (Punkte bzw. Mittelpunkte von Wegen) mit passenden Tags im Gebiet -> Liste wie Overpass 'elements'."""
    conds = _parse_filter(tag_filter)
    s, w, n, e = bbox
    out = []
    for lat, lon, typ, oid, tags in load()["objects"]:
        if s <= lat <= n and w <= lon <= e and _match(tags, conds):
            out.append({"type": typ, "id": oid, "lat": lat, "lon": lon, "tags": tags})
    return out


def _haversine(lat1, lon1, lat2, lon2):
    r = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    return 2 * r * math.asin(math.sqrt(math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2))


def intersection(street_a, street_b):
    """Gemeinsame Knoten zweier Straßen -> Gruppen (lat, lon, anzahl), größte zuerst."""
    d = load()
    common = d["streets"].get(street_a, set()) & d["streets"].get(street_b, set())
    groups = []
    for ref in common:
        lat, lon = d["coords"][ref]
        for g in groups:
            if _haversine(lat, lon, g[0], g[1]) < 150:
                g[2].append((lat, lon))
                break
        else:
            groups.append([lat, lon, [(lat, lon)]])
    result = [(sum(p[0] for p in g[2]) / len(g[2]), sum(p[1] for p in g[2]) / len(g[2]), len(g[2])) for g in groups]
    return sorted(result, key=lambda t: -t[2])


def find_name(name):
    """Erstes Objekt mit genau diesem Namen (Groß/klein egal) -> (lat, lon, tags) oder None."""
    target = name.strip().casefold()
    for lat, lon, _, _, tags in load()["objects"]:
        if tags.get("name", "").casefold() == target:
            return lat, lon, tags
    return None


def drive_graph(lat, lon, radius_m):
    """Straßennetz für Autos im Quadrat ±radius_m um den Punkt, im Format wie osmnx (crs EPSG:4326)."""
    d = load()
    dlat = radius_m / 111320
    dlon = radius_m / (111320 * math.cos(math.radians(lat)))
    s, n, w, e = lat - dlat, lat + dlat, lon - dlon, lon + dlon
    coords = d["coords"]
    G = nx.MultiDiGraph(crs="EPSG:4326")
    for wid, refs, tags in d["drive_ways"]:
        refs = [r for r in refs if r in coords]
        if not any(s <= coords[r][0] <= n and w <= coords[r][1] <= e for r in refs):
            continue
        oneway = tags.get("oneway")
        forward = oneway not in ("-1",)
        backward = not (oneway in ("yes", "true", "1", "-1") or tags.get("junction") in ("roundabout", "circular")
                        or tags.get("highway") == "motorway") or oneway == "-1"
        for a, b in zip(refs[:-1], refs[1:]):
            for r in (a, b):
                if r not in G:
                    G.add_node(r, y=coords[r][0], x=coords[r][1])
            length = _haversine(coords[a][0], coords[a][1], coords[b][0], coords[b][1])
            attrs = dict(tags, osmid=wid, length=length)
            if forward:
                G.add_edge(a, b, **attrs)
            if backward:
                G.add_edge(b, a, **attrs)
    outside = [x for x, nd in G.nodes(data=True) if not (s <= nd["y"] <= n and w <= nd["x"] <= e)]
    G.remove_nodes_from(outside)
    if G.number_of_nodes() == 0:
        raise ValueError("Kein Straßennetz in der lokalen Region an diesem Punkt.")
    biggest = max(nx.weakly_connected_components(G), key=len)
    return G.subgraph(biggest).copy()


# ---------- Flächen (Umrisse) für Starkregen/Hitze ----------
# Die Region-Datei oben kennt Gebäude und Flächen nur als Mittelpunkt. Für Versiegelung, Baumkronen usw.
# braucht es die Umrisse. Die stehen in einer zweiten Datei (areas_*.pkl), einmalig erzeugt mit
#     python local_osm.py areas
AREA_KEYS = ("name", "building", "landuse", "natural", "leisure", "amenity", "area:highway", "highway", "water",
             "waterway", "place", "surface", "parking", "building:levels", "height", "area", "layer",
             "tunnel", "covered", "diameter_crown")
_AREAS = None


def _areas_path():
    key = hashlib.sha1(f"{REGION}".encode()).hexdigest()[:10]
    return os.path.join(os.path.dirname(PBF), f"areas_{key}.pkl")


def areas_available():
    return SOURCE != "online" and os.path.exists(_areas_path())


def areas_cover(bbox):
    s, w, n, e = bbox
    return areas_available() and _in_region(s, w) and _in_region(n, e)


def prepare_areas():
    """Umrisse von Gebäuden, Flächennutzung, Grünflächen, Wasser sowie Wege/Baumreihen als Linien
    aus der .pbf-Datei ausschneiden (einmalig, einige Minuten)."""
    import osmium

    if not os.path.exists(PBF):
        raise FileNotFoundError(f"OSM-Datei fehlt: {PBF} (Download: download.geofabrik.de, Hessen)")
    start = time.time()
    polys, lines = [], []
    s, w, n, e = REGION

    def ring_coords(ring):
        return [(round(nd.lon, 6), round(nd.lat, 6)) for nd in ring if nd.location.valid()]

    def in_box(pts):
        lons = [p[0] for p in pts]
        lats = [p[1] for p in pts]
        return pts and min(lats) <= n and max(lats) >= s and min(lons) <= e and max(lons) >= w

    fp = (osmium.FileProcessor(PBF).with_locations().with_areas()
          .with_filter(osmium.filter.KeyFilter("building", "landuse", "natural", "leisure", "amenity",
                                               "area:highway", "highway", "water", "waterway", "place")))
    for obj in fp:
        if obj.is_area():
            tags = {k: obj.tags[k] for k in AREA_KEYS if k in obj.tags}
            if "highway" in tags and tags.get("area") != "yes":
                continue  # geschlossene Straßen (Kreisverkehr) sind keine Flächen
            rings = []
            for outer in obj.outer_rings():
                pts = ring_coords(outer)
                if len(pts) >= 4 and in_box(pts):
                    rings.append((pts, [ring_coords(inner) for inner in obj.inner_rings(outer)]))
            if rings:
                polys.append((tags, rings))
        elif obj.is_way():
            hw = obj.tags.get("highway")
            if (hw and obj.tags.get("area") != "yes") or obj.tags.get("natural") == "tree_row":
                pts = [(round(nd.lon, 6), round(nd.lat, 6)) for nd in obj.nodes if nd.location.valid()]
                if len(pts) >= 2 and in_box(pts):
                    lines.append(({k: obj.tags[k] for k in AREA_KEYS if k in obj.tags}, pts))
    data = {"region": REGION, "polys": polys, "lines": lines}
    with open(_areas_path(), "wb") as f:
        pickle.dump(data, f, protocol=pickle.HIGHEST_PROTOCOL)
    print(f"Flächen gespeichert: {len(polys)} Flächen, {len(lines)} Linien, {time.time() - start:.0f}s -> {_areas_path()}")
    return data


def areas(bbox):
    """Flächen und Linien, die das Gebiet (süd, west, nord, ost) berühren.
    -> (polys [(tags, [(außenring, [innenringe])])], lines [(tags, punkte)]), Koordinaten als (lon, lat)."""
    global _AREAS
    if _AREAS is None:
        with open(_areas_path(), "rb") as f:
            _AREAS = pickle.load(f)

        def box(pts):
            return (min(p[1] for p in pts), min(p[0] for p in pts), max(p[1] for p in pts), max(p[0] for p in pts))
        _AREAS["poly_box"] = [box([p for o, _ in r for p in o]) for _, r in _AREAS["polys"]]
        _AREAS["line_box"] = [box(p) for _, p in _AREAS["lines"]]
    s, w, n, e = bbox

    def overlaps(b):
        return b[0] <= n and b[2] >= s and b[1] <= e and b[3] >= w

    polys = [p for p, b in zip(_AREAS["polys"], _AREAS["poly_box"]) if overlaps(b)]
    lines = [p for p, b in zip(_AREAS["lines"], _AREAS["line_box"]) if overlaps(b)]
    return polys, lines


if __name__ == "__main__":
    import sys

    prepare_areas() if sys.argv[1:] == ["areas"] else prepare()
