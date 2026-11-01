"""
Baustellen-Analyse (Stufe 1, grobe Abschätzung): Ort finden, Verkehrsverlagerung, Baulärm.
Methode und Grenzen: docs/baustellen-analyse.md

  geocode(ort)                          -> Koordinaten (auch Kreuzungen "Straße A / Straße B, Stadt")
  traffic_impact(lat, lon, ...)         -> welche Straßen mehr/weniger Verkehr bekommen, Umwege, Verkehrslärm
  construction_noise(lat, lon, ...)     -> Lärmringe, betroffene Gebäude und sensible Einrichtungen
"""
import hashlib
import json
import math
import os
import random
import re
import statistics
import time
import urllib.parse
import urllib.request

import networkx as nx
import osmnx as ox
from pyproj import Transformer
from shapely.geometry import LineString, Point, mapping
from shapely.ops import transform as shp_transform

import annahmen as annahmen_mod
import geo_tools
import local_osm

CACHE = geo_tools.CACHE_DIR
os.makedirs(CACHE, exist_ok=True)
ox.settings.cache_folder = os.path.join(CACHE, "osmnx")
ox.settings.overpass_rate_limit = False   # Status-Abfrage hängt, wenn overpass-api.de streikt
ox.settings.requests_timeout = 60
ox.settings.http_user_agent = "uni-qgis-prototype"
ox.settings.log_console = False

TO_UTM = Transformer.from_crs("EPSG:4326", "EPSG:25832", always_xy=True)
TO_WGS = Transformer.from_crs("EPSG:25832", "EPSG:4326", always_xy=True)

# Schallleistungspegel Lw in dB(A), typische Größenordnungen
NOISE_ACTIVITY = {
    "normal": (105, "Bagger, Lkw, Radlader"),
    "laut": (112, "Abbruch, Stemmen, Betonsägen"),
    "sehr_laut": (120, "Rammen, Spundwände, Presslufthammer im Dauerbetrieb"),
}
KIND_DE = {"hospital": "Krankenhaus", "clinic": "Klinik", "nursing_home": "Pflegeheim",
           "social_facility": "Soziale Einrichtung", "school": "Schule", "kindergarten": "Kita",
           "childcare": "Kinderbetreuung"}
RING_COLORS = ["#fef0d9", "#fdcc8a", "#fc8d59", "#d7301f", "#7f0000"]   # leise -> laut


# ---------- Annahmen: alle vom Agenten anpassbar (Parameter "annahmen"), Ergebnis enthält die Tabelle ----------
def _a(wert, einheit, info):
    return {"wert": wert, "einheit": einheit, "info": info}


VERKEHR_DEFAULTS = {
    "untersuchungsradius_m": _a(1500, "m", "Straßennetz im Umkreis um die Baustelle"),
    "sperrung_m": _a(30, "m", "alle Straßenabschnitte bis zu diesem Abstand werden gesperrt"),
    "fahrten": _a(1500, "Anzahl", "simulierte Durchgangsfahrten"),
    "rand_ab_radius_anteil": _a(0.6, "Anteil", "Start/Ziel der Fahrten liegen außerhalb dieses Anteils des Radius"),
    "min_fahrtlaenge_anteil": _a(1.0, "Anteil", "Start und Ziel mindestens so weit auseinander (x Radius)"),
    "grundverkehr_faktor": _a(1.0, "x Median", "Grundverkehr je Abschnitt (Anwohner, Lieferverkehr) als Vielfaches des Medians"),
    "zufallsstart": _a(42, "-", "Startwert des Zufalls (gleich = gleiches Ergebnis)"),
}
LAERM_DEFAULTS = {
    "schallleistung_db": _a({"normal": 105, "laut": 112, "sehr_laut": 120}, "dB(A)",
                            "Schallleistung Lw je Tätigkeit (Bagger/Lkw, Abbruch, Rammen)"),
    "bodendaempfung_db": _a(8, "dB", "Abzug für Punktquelle über Boden: L = Lw - 20 log10(r) - Abzug"),
    "mindestabstand_m": _a(5, "m", "kleinster Abstand in der Formel (direkt an der Quelle)"),
    "laermring_unterster_db": _a(55, "dB(A)", "unterster Lärmring; darüber 4 weitere in 5-dB-Schritten"),
    "richtwerte_db": _a({"krankenhaus": 45, "pflege": 45, "soziale_einrichtung": 45, "schule": 55, "kita": 55,
                         "sonst": 55}, "dB(A)", "Immissionsrichtwerte tags (AVV Baulärm; Schule/Kita wie allg. Wohngebiet)"),
}
annahmen_mod.wichtig(VERKEHR_DEFAULTS, "sperrung_m", "fahrten", "grundverkehr_faktor")
annahmen_mod.wichtig(LAERM_DEFAULTS, "schallleistung_db", "bodendaempfung_db", "richtwerte_db")
LIMIT_KEY = {"hospital": "krankenhaus", "clinic": "krankenhaus", "nursing_home": "pflege",
             "social_facility": "soziale_einrichtung", "school": "schule", "kindergarten": "kita", "childcare": "kita"}


def _out(name):
    return geo_tools.out_path(name)


def _write_geojson(path, features):
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": features}, f, ensure_ascii=False)
    return path


def _to_wgs(geom):
    return shp_transform(lambda x, y, z=None: TO_WGS.transform(x, y), geom)


# ---------- Ort finden ----------
def _cached_json(key, fn):
    path = os.path.join(CACHE, "geo_" + hashlib.sha1(key.encode()).hexdigest()[:16] + ".json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    result = fn()
    if result:  # Fehlschläge nicht speichern, sonst bleibt der Ort für immer "nicht gefunden"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False)
    return result


def _nominatim(query):
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
        {"q": query, "format": "jsonv2", "limit": 1, "countrycodes": "de"})
    req = urllib.request.Request(url, headers={"User-Agent": "uni-qgis-prototype"})
    with urllib.request.urlopen(req, timeout=20) as r:
        hits = json.load(r)
    time.sleep(1)  # Nutzungsregeln Nominatim: max. 1 Anfrage pro Sekunde
    if not hits:
        return None
    return {"lat": float(hits[0]["lat"]), "lon": float(hits[0]["lon"]), "name": hits[0]["display_name"],
            "method": "Adresssuche (Nominatim)"}


def _intersection(street_a, street_b, city):
    """Kreuzungspunkt zweier Straßen über Overpass (gemeinsame Knoten beider Straßen)."""
    query = f"""[out:json][timeout:25];
    area["name"="{city}"]["boundary"="administrative"]->.a;
    way(area.a)["highway"]["name"="{street_a}"]->.w1;
    way(area.a)["highway"]["name"="{street_b}"]->.w2;
    node(w.w1)(w.w2);
    out;"""
    osm, _ = geo_tools._overpass(query)
    nodes = osm.get("elements", [])
    if not nodes:
        return None
    lat = sum(n["lat"] for n in nodes) / len(nodes)
    lon = sum(n["lon"] for n in nodes) / len(nodes)
    return {"lat": lat, "lon": lon, "name": f"{street_a} / {street_b}, {city}",
            "method": f"Kreuzung ({len(nodes)} gemeinsame Knoten)"}


def geocode(place):
    """Adresse, Ort oder Kreuzung ("Rheinstraße / Neckarstraße, Darmstadt") -> lat/lon."""
    def safe(fn, *args):
        try:
            return fn(*args)
        except Exception as err:
            print(f"  {fn.__name__} fehlgeschlagen: {err}")
            return None

    def lookup():
        first = place.split(",", 1)[0].strip()
        if "," in place:
            streets, city = place.split(",", 1)
            parts = [p.strip() for p in re.split(r"\s*(?:/|&|\bEcke\b|\bund\b|\bx\b)\s*", streets) if p.strip()]
            if len(parts) == 2:
                if local_osm.available():
                    groups = local_osm.intersection(parts[0], parts[1])
                    if groups:
                        best = groups[0]
                        if len(groups) > 1:  # gleiche Straßennamen in Nachbarorten: der Stadtmitte am nächsten
                            center = safe(_nominatim, city.strip())
                            if center:
                                best = min(groups, key=lambda g: (g[0] - center["lat"]) ** 2 + (g[1] - center["lon"]) ** 2)
                        return {"lat": best[0], "lon": best[1], "name": f"{parts[0]} / {parts[1]}, {city.strip()}",
                                "method": f"Kreuzung aus lokalen OSM-Daten ({best[2]} gemeinsame Knoten)"}
                hit = safe(_intersection, parts[0], parts[1], city.strip())
                if hit:
                    return hit
        hit = safe(_nominatim, place)
        if hit:
            return hit
        if local_osm.available():
            found = local_osm.find_name(first)
            if found:
                return {"lat": found[0], "lon": found[1], "name": first, "method": "Namenssuche in lokalen OSM-Daten"}
        return None

    result = _cached_json("geocode:" + place.strip().lower(), lookup)
    if not result:
        raise ValueError(f"Ort '{place}' nicht gefunden. Bei Kreuzungen Format 'Straße A / Straße B, Stadt' nutzen.")
    return result


# ---------- Verkehr ----------
def _load_graph(lat, lon, radius_m):
    dlat = radius_m / 111320
    dlon = radius_m / (111320 * math.cos(math.radians(lat)))
    if local_osm.covers((lat - dlat, lon - dlon, lat + dlat, lon + dlon)):
        return local_osm.drive_graph(lat, lon, radius_m)
    path =os.path.join(CACHE, f"graph_{lat:.4f}_{lon:.4f}_{int(radius_m)}.graphml")
    if os.path.exists(path):
        return ox.load_graphml(path)
    last_error = None
    for url in geo_tools.OVERPASS_SERVERS:
        ox.settings.overpass_url = url.rsplit("/interpreter", 1)[0]
        try:
            G = ox.graph_from_point((lat, lon), dist=radius_m, network_type="drive")
            ox.save_graphml(G, path)
            return G
        except Exception as err:
            last_error = err
            print(f"  Straßennetz über {url} fehlgeschlagen ({err}), versuche nächsten ...")
    raise RuntimeError(f"Straßennetz konnte nicht geladen werden (Overpass überlastet?): {last_error}")


def _edge_name(data):
    for key in ("name", "ref"):
        val = data.get(key)
        if isinstance(val, list):
            val = " / ".join(dict.fromkeys(str(v) for v in val))
        if isinstance(val, str) and val:
            return val
    hw = data.get("highway")
    return f"(unbenannt, {hw if isinstance(hw, str) else 'Straße'})"


def _path_edges(G, path):
    return list(zip(path[:-1], path[1:]))


def _path_length(G, path):
    return sum(min(d["length"] for d in G[u][v].values()) for u, v in _path_edges(G, path))


def traffic_impact(lat, lon, radius_m=None, closure_m=None, trips=None, prefix="baustelle", annahmen=None):
    """Verkehrsverlagerung bei Sperrung aller Straßenabschnitte bis closure_m um (lat, lon).
    annahmen: dict mit geänderten Werten aus VERKEHR_DEFAULTS."""
    over = dict(annahmen or {})
    for key, val in (("untersuchungsradius_m", radius_m), ("sperrung_m", closure_m), ("fahrten", trips)):
        if val is not None:
            over.setdefault(key, val)
    A, tabelle = annahmen_mod.anwenden(VERKEHR_DEFAULTS, over)
    radius_m, closure_m, trips = A["untersuchungsradius_m"], A["sperrung_m"], int(A["fahrten"])
    G = ox.project_graph(_load_graph(lat, lon, radius_m), to_crs="EPSG:25832")
    x0, y0 = TO_UTM.transform(lon, lat)
    site = Point(x0, y0)

    edges = ox.graph_to_gdfs(G, nodes=False)
    dist = edges.geometry.distance(site)
    closed = edges[dist <= closure_m]
    if closed.empty:
        closed = edges[dist <= dist.min() + 1]
    closed_pairs = {(u, v) for u, v, _ in closed.index}

    H = G.copy()
    H.remove_edges_from(list(closed.index))

    # Durchgangsverkehr: Fahrten zwischen Punkten am Rand des Gebiets, quer durch die Mitte
    rim = [n for n, d in G.nodes(data=True) if math.hypot(d["x"] - x0, d["y"] - y0) > A["rand_ab_radius_anteil"] * radius_m]
    rng = random.Random(int(A["zufallsstart"]))
    base, after = {}, {}
    detours, unreachable, n_trips, n_affected = [], 0, 0, 0
    for _ in range(trips * 3):
        if n_trips >= trips or len(rim) < 2:
            break
        o, d = rng.sample(rim, 2)
        do, dd = G.nodes[o], G.nodes[d]
        if math.hypot(do["x"] - dd["x"], do["y"] - dd["y"]) < A["min_fahrtlaenge_anteil"] * radius_m:
            continue
        try:
            p0 = nx.shortest_path(G, o, d, weight="length")
        except nx.NetworkXNoPath:
            continue
        n_trips += 1
        e0 = _path_edges(G, p0)
        for e in e0:
            base[e] = base.get(e, 0) + 1
        if not closed_pairs.intersection(e0):
            for e in e0:
                after[e] = after.get(e, 0) + 1
            continue
        n_affected += 1
        try:
            p1 = nx.shortest_path(H, o, d, weight="length")
        except nx.NetworkXNoPath:
            unreachable += 1
            continue
        detours.append(_path_length(H, p1) - _path_length(G, p0))
        for e in _path_edges(H, p1):
            after[e] = after.get(e, 0) + 1

    # Ergebnis je Straßenabschnitt
    changed = {e for e in set(base) | set(after) if base.get(e, 0) != after.get(e, 0) and e not in closed_pairs}
    max_delta = max((abs(after.get(e, 0) - base.get(e, 0)) for e in changed), default=1)
    # Grundverkehr (Anwohner, Lieferverkehr ...), den das Durchgangsmodell nicht kennt: ohne ihn würde eine
    # ruhige Nebenstraße bei 0 starten und die dB-Änderung wäre stark übertrieben
    grund = statistics.median([c for c in base.values() if c > 0] or [1]) * A["grundverkehr_faktor"]
    feats, by_street = [], {}
    for u, v in changed:
        data = min(G[u][v].values(), key=lambda d: d["length"])
        b, a = base.get((u, v), 0), after.get((u, v), 0)
        delta = a - b
        db = round(10 * math.log10((a + grund) / (b + grund)), 1)
        name = _edge_name(data)
        s = by_street.setdefault(name, {"plus": 0, "minus": 0, "max_db": None})
        s["plus"], s["minus"] = max(s["plus"], delta), min(s["minus"], delta)
        if delta > 0:
            s["max_db"] = max(s["max_db"] or 0, db)
        geom = data.get("geometry") or LineString(
            [(G.nodes[u]["x"], G.nodes[u]["y"]), (G.nodes[v]["x"], G.nodes[v]["y"])])
        laerm = f"{db:+.1f} dB"
        feats.append({"type": "Feature", "geometry": mapping(_to_wgs(geom)), "properties": {
            "name": name, "vorher": b, "nachher": a, "delta": delta, "laerm_aenderung_db": db,
            "_style": {"color": "#d7191c" if delta > 0 else "#1a9641", "weight": 2 + round(6 * abs(delta) / max_delta),
                       "opacity": 0.85},
            "_popup": f"<b>{name}</b><br>Durchgangsfahrten: {b} → {a} ({delta:+d})<br>Verkehrslärm: {laerm}"}})
    traffic_path = _write_geojson(_out(f"{prefix}_verkehr.geojson"), feats)

    closure_feats = []
    for (u, v, k), row in closed.iterrows():
        closure_feats.append({"type": "Feature", "geometry": mapping(_to_wgs(row.geometry)), "properties": {
            "name": _edge_name(row), "_style": {"color": "#000000", "weight": 8, "dashArray": "6 6"},
            "_popup": f"<b>Gesperrt:</b> {_edge_name(row)}"}})
    closure_path = _write_geojson(_out(f"{prefix}_sperrung.geojson"), closure_feats)

    more = sorted(((n, s) for n, s in by_street.items() if s["plus"] > 0), key=lambda t: -t[1]["plus"])[:8]
    less = sorted(((n, s) for n, s in by_street.items() if s["minus"] < 0), key=lambda t: t[1]["minus"])[:8]

    return {
        "files": {"verkehr": traffic_path, "sperrung": closure_path},
        "annahmen": tabelle,
        "gesperrte_strassen": sorted({_edge_name(r) for _, r in closed.iterrows()}),
        "modell": f"{n_trips} simulierte Durchgangsfahrten (kürzester Weg) im Umkreis {radius_m} m",
        "betroffene_fahrten": n_affected,
        "betroffene_fahrten_prozent": round(100 * n_affected / max(n_trips, 1), 1),
        "umweg_m": {"mittel": round(statistics.mean(detours)) if detours else 0,
                    "median": round(statistics.median(detours)) if detours else 0,
                    "max": round(max(detours)) if detours else 0},
        "nicht_mehr_erreichbar": unreachable,
        "mehr_verkehr": [{"strasse": n, "zusaetzliche_fahrten": s["plus"],
                          **({"verkehrslaerm_max_db": s["max_db"]} if s["max_db"] else {})} for n, s in more],
        "weniger_verkehr": [{"strasse": n, "weniger_fahrten": -s["minus"]} for n, s in less],
        "hinweis": "Relative Verlagerung des Durchgangsverkehrs, keine echten Fahrzeugzahlen. "
                   "Verkehrslärm: 10·log10(nachher/vorher) inkl. angenommenem Grundverkehr "
                   f"({grund:g} Fahrten je Abschnitt), doppelter Verkehr ≈ +3 dB.",
    }


# ---------- Baulärm ----------
def _level(lw, r, A=None):
    A = A or {"mindestabstand_m": 5, "bodendaempfung_db": 8}
    return lw - 20 * math.log10(max(r, A["mindestabstand_m"])) - A["bodendaempfung_db"]


def construction_noise(lat, lon, activity="normal", lw_db=None, prefix="baustelle", annahmen=None):
    """Lärmringe einer Baustelle + betroffene Gebäude / sensible Einrichtungen.
    annahmen: dict mit geänderten Werten aus LAERM_DEFAULTS."""
    A, tabelle = annahmen_mod.anwenden(LAERM_DEFAULTS, annahmen)
    activity = activity if activity in NOISE_ACTIVITY else "normal"
    lw, desc = (lw_db, "eigener Wert") if lw_db else (A["schallleistung_db"][activity], NOISE_ACTIVITY[activity][1])
    low = A["laermring_unterster_db"]
    levels = [low + 20, low + 15, low + 10, low + 5, low]
    radius = {L: 10 ** ((lw - A["bodendaempfung_db"] - L) / 20) for L in levels}
    x0, y0 = TO_UTM.transform(lon, lat)
    site = Point(x0, y0)

    ring_feats = []
    for i, L in enumerate(sorted(levels)):            # außen (55) zuerst, damit innen oben liegt
        outer = site.buffer(radius[L], 64)
        upper = L + 5
        geom = outer.difference(site.buffer(radius[upper], 64)) if upper in radius else outer
        label = f"{L}–{upper} dB(A)" if upper in radius else f"über {L} dB(A)"
        ring_feats.append({"type": "Feature", "geometry": mapping(_to_wgs(geom)), "properties": {
            "name": label, "pegel_ab": L, "radius_m": round(radius[L]),
            "_style": {"color": RING_COLORS[i], "fillColor": RING_COLORS[i], "fillOpacity": 0.35, "weight": 1},
            "_popup": f"<b>Baulärm {label}</b><br>bis {round(radius[L])} m von der Baustelle"}})
    ring_feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]}, "properties": {
        "name": "Baustelle", "_style": {"radius": 9, "fillColor": "#000000", "color": "#ffeb3b", "weight": 3},
        "_popup": f"<b>Baustelle</b><br>Lw = {lw} dB(A) ({desc})"}})
    rings_path = _write_geojson(_out(f"{prefix}_laermringe.geojson"), ring_feats)

    # OSM-Daten im Umkreis des untersten Rings
    r55 = radius[low]
    lon_min, lat_min = TO_WGS.transform(x0 - r55, y0 - r55)
    lon_max, lat_max = TO_WGS.transform(x0 + r55, y0 + r55)
    bbox = (lat_min, lon_min, lat_max, lon_max)
    buildings = geo_tools.fetch_osm('"building"', bbox, _out(f"{prefix}_gebaeude_roh.geojson"))
    sensitive = geo_tools.fetch_osm('"amenity"~"^(school|kindergarten|childcare|hospital|clinic|nursing_home|social_facility)$"',
                                    bbox, _out(f"{prefix}_einrichtungen_roh.geojson"))

    def located(path):
        with open(path, encoding="utf-8") as f:
            for feat in json.load(f)["features"]:
                lo, la = feat["geometry"]["coordinates"]
                x, y = TO_UTM.transform(lo, la)
                d = math.hypot(x - x0, y - y0)
                if d <= r55:
                    yield feat, d, _level(lw, d, A)

    band_counts = {f"ab {L} dB(A)": 0 for L in levels}
    for _, _, lvl in located(buildings["path"]):
        for L in levels:
            if lvl >= L:
                band_counts[f"ab {L} dB(A)"] += 1

    sens_list, sens_feats = [], []
    for feat, d, lvl in located(sensitive["path"]):
        p = feat["properties"]
        kind = p.get("amenity", "")
        limit = A["richtwerte_db"][LIMIT_KEY.get(kind, "sonst")]
        name = p.get("name") or KIND_DE.get(kind, kind)
        over = lvl > limit
        sens_list.append({"name": name, "art": KIND_DE.get(kind, kind), "entfernung_m": round(d),
                          "pegel_db": round(lvl), "richtwert_db": limit, "ueberschritten": over})
        feat["properties"].update({
            "_style": {"radius": 8, "fillColor": "#6a3d9a" if over else "#1f78b4", "color": "#ffffff", "weight": 2},
            "_popup": f"<b>{name}</b> ({KIND_DE.get(kind, kind)})<br>ca. {round(lvl)} dB(A) in {round(d)} m"
                      f"<br>Richtwert {limit} dB(A): {'<b>überschritten</b>' if over else 'eingehalten'}"})
        sens_feats.append(feat)
    sens_path = _write_geojson(_out(f"{prefix}_einrichtungen.geojson"), sens_feats)
    sens_list.sort(key=lambda s: -s["pegel_db"])

    return {
        "files": {"laermringe": rings_path, "einrichtungen": sens_path},
        "annahmen": tabelle,
        "schallleistung_lw_db": lw, "taetigkeit": desc,
        "radius_m": {f"{L} dB(A)": round(r) for L, r in radius.items()},
        "gebaeude_mit_pegel": band_counts,
        "sensible_einrichtungen": sens_list[:15],
        "richtwerte_avv_baulaerm_tags": {"Krankenhäuser/Pflege": 45, "reine Wohngebiete": 50,
                                         "allgemeine Wohngebiete": 55, "Mischgebiete": 60},
        "hinweis": "Freifeld-Abschätzung ohne Abschirmung durch Gebäude, keine Berechnung nach Vorschrift. "
                   "Pegel an Gebäuden = Gebäudemittelpunkt.",
    }
