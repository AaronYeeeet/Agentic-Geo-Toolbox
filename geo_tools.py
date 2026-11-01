"""
Geo-Tools ohne QGIS-Fenster: "Wo kann ich neue Ladesäulen bauen?" (Darmstadt)

Läuft mit normalem Python (z.B. aus VS Code), ruft QGIS im Hintergrund über `qgis_process` auf.
Jede Funktion unten ist so gebaut, dass ein LLM-Agent sie später als Tool aufrufen kann:

  fetch_osm(tag, bbox)          -> Daten von OpenStreetMap holen (GeoJSON)
  list_algorithms(filter)       -> welche QGIS-Werkzeuge gibt es?
  algorithm_help(alg_id)        -> welche Parameter braucht ein Werkzeug?
  run_algorithm(alg_id, params) -> Werkzeug ausführen

Ergebnis: Ordner ./output mit GeoJSON-Dateien + karte.html (im Browser öffnen).
"""
import hashlib
import json
import os
import re
import subprocess
import time
import urllib.parse
import urllib.request

from dotenv import load_dotenv

import local_osm

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
QGIS_PROCESS = os.environ.get(
    "QGIS_PROCESS", r"C:\Program Files\QGIS 3.44.15\bin\qgis_process-qgis-ltr.bat")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
os.makedirs(OUT, exist_ok=True)

OVERPASS_SERVERS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]
OVERPASS_TIMEOUT = 25    # Sekunden pro Server; hängende Server nicht ewig abwarten
CACHE_DIR = os.path.join(OUT, "cache")
RESULTS_DIR = os.path.join(OUT, "ergebnisse")   # ein Unterordner pro Frage, siehe new_run()
_run_dir = OUT                                    # aktueller Ergebnisordner (ohne Frage: output/)


def new_run(label):
    """Neuen Ergebnisordner output/ergebnisse/<Datum_Uhrzeit>_<Stichwort>/ anlegen und als aktuellen setzen."""
    global _run_dir
    slug = re.sub(r"[^a-z0-9äöüß]+", "_", label.lower()).strip("_")[:40] or "frage"
    _run_dir = os.path.join(RESULTS_DIR, time.strftime("%Y-%m-%d_%H-%M-%S_") + slug)
    os.makedirs(_run_dir, exist_ok=True)
    return _run_dir


def run_dir():
    return _run_dir


def out_path(name):
    """Pfad für eine NEUE Datei: relative Namen landen im aktuellen Ergebnisordner."""
    return name if os.path.isabs(name) else os.path.join(_run_dir, name)


def find_path(name):
    """Pfad für eine VORHANDENE Datei: erst aktueller Ergebnisordner, dann frühere Ordner (neueste zuerst),
    dann output/. So findet der Agent auch Dateien aus einer früheren Frage im selben Chat."""
    if os.path.isabs(name):
        return name
    folders = [_run_dir]
    if os.path.isdir(RESULTS_DIR):
        folders += [os.path.join(RESULTS_DIR, d) for d in sorted(os.listdir(RESULTS_DIR), reverse=True)][:30]
    for folder in folders + [OUT]:
        candidate = os.path.join(folder, name)
        if os.path.exists(candidate):
            return candidate
    return out_path(name)
CACHE_MAX_AGE_DAYS = 7   # danach werden die Daten neu geladen


def _overpass(query, timeout=OVERPASS_TIMEOUT, rounds=2):
    """Fragt die Overpass-Server der Reihe nach. Ein Server, der funktioniert hat, wird
    nach vorne sortiert und beim nächsten Mal zuerst gefragt. Kürzere timeout/rounds = schneller aufgeben."""
    data = urllib.parse.urlencode({"data": query}).encode()
    last_error = None
    for attempt in range(rounds):
        for url in list(OVERPASS_SERVERS):
            try:
                req = urllib.request.Request(url, data=data, headers={"User-Agent": "uni-qgis-prototype"})
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    osm = json.load(r)
                OVERPASS_SERVERS.remove(url)
                OVERPASS_SERVERS.insert(0, url)
                return osm, url
            except Exception as err:
                last_error = err
                print(f"  {url} nicht erreichbar ({err}), versuche nächsten ...")
        if attempt < rounds - 1:
            time.sleep(5)
    raise RuntimeError(f"Kein Overpass-Server erreichbar (OpenStreetMap-Abfragedienst überlastet): {last_error}")


# ---------- Tool: Daten holen ----------
def fetch_osm(tag_filter, bbox, out_path):
    """Holt OSM-Objekte (Punkte, Flächen als Mittelpunkt) im Gebiet bbox=(süd, west, nord, ost).
    Ergebnisse werden zwischengespeichert: gleiche Abfrage -> sofort von der Platte, ohne Server."""
    s, w, n, e = (round(float(v), 5) for v in bbox)
    query = f"""[out:json][timeout:{OVERPASS_TIMEOUT}];
    (node[{tag_filter}]({s},{w},{n},{e});
     way[{tag_filter}]({s},{w},{n},{e}););
    out center tags;"""

    os.makedirs(CACHE_DIR, exist_ok=True)
    cache_file = os.path.join(CACHE_DIR, "osm_" + hashlib.sha1(query.encode()).hexdigest()[:16] + ".json")
    fresh = os.path.exists(cache_file) and time.time() - os.path.getmtime(cache_file) < CACHE_MAX_AGE_DAYS * 86400
    if local_osm.covers((s, w, n, e)):
        # Lokale Geofabrik-Daten: schnell, offline, keine überlasteten Server
        osm = {"elements": local_osm.query(tag_filter, (s, w, n, e))}
        source = f"lokal (Geofabrik, Stand {local_osm.stand()})"
    elif local_osm.SOURCE == "local":
        raise ValueError(f"Gebiet {bbox} liegt außerhalb der lokalen Region {local_osm.REGION} (OSM_SOURCE=local).")
    elif fresh:
        with open(cache_file, encoding="utf-8") as f:
            osm = json.load(f)
        source = "cache"
    else:
        osm, source = _overpass(query)
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(osm, f)

    features = []
    for el in osm["elements"]:
        lat = el.get("lat", el.get("center", {}).get("lat"))
        lon = el.get("lon", el.get("center", {}).get("lon"))
        if lat is None:
            continue
        tags = el.get("tags", {})
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {"osm_id": el["id"], "name": tags.get("name", ""),
                           "amenity": tags.get("amenity", ""), "building": tags.get("building", ""),
                           "operator": tags.get("operator", ""), "capacity": tags.get("capacity", "")},
        })
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": features}, f)
    return {"path": out_path, "count": len(features), "source": source}


# ---------- Tools: QGIS ----------
def _qgis(*args, stdin=None):
    result = subprocess.run([QGIS_PROCESS, *args], input=stdin, capture_output=True,
                            text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise RuntimeError(f"qgis_process {' '.join(args)} fehlgeschlagen:\n{result.stderr or result.stdout}")
    return result.stdout


def _json_part(text):
    # qgis_process schreibt manchmal Warnungen vor das JSON
    return json.loads(text[text.index("{"):])


_ALL_ALGS = None   # Zwischenspeicher: qgis_process ist langsam (startet QGIS jedes Mal neu)
_HELP_CACHE = {}


def list_algorithms(filter_text=""):
    """Liste aller QGIS-Algorithmen (id + Name), optional gefiltert."""
    global _ALL_ALGS
    if _ALL_ALGS is None:
        data = _json_part(_qgis("list", "--json"))
        _ALL_ALGS = [{"id": alg_id, "name": alg["name"]}
                     for provider in data["providers"].values()
                     for alg_id, alg in provider["algorithms"].items()]
    return [a for a in _ALL_ALGS if filter_text.lower() in (a["id"] + " " + a["name"]).lower()]


def algorithm_help(alg_id):
    """Beschreibung + Parameter eines Algorithmus (für das LLM)."""
    if alg_id not in _HELP_CACHE:
        _HELP_CACHE[alg_id] = _json_part(_qgis("help", alg_id, "--json"))
    return _HELP_CACHE[alg_id]


def run_algorithm(alg_id, params):
    """Führt einen QGIS-Algorithmus aus. params wie in QGIS, z.B. {"INPUT": "a.geojson", "OUTPUT": "b.geojson"}."""
    out = _qgis("run", alg_id, "-", stdin=json.dumps({"inputs": params}))
    return _json_part(out)["results"]


# ---------- Demo-Ablauf (das, was der Agent selbst planen soll) ----------
def demo():
    bbox = (49.860, 8.630, 49.885, 8.680)  # Darmstadt Innenstadt + Lichtwiese
    buffer_m = 400
    p = lambda name: os.path.join(OUT, name)

    print("1. Daten von OpenStreetMap ...")
    chargers = fetch_osm('"amenity"="charging_station"', bbox, p("ladesaeulen.geojson"))
    parking = fetch_osm('"amenity"="parking"', bbox, p("parkplaetze.geojson"))
    print(f"   Ladesäulen: {chargers['count']}, Parkplätze: {parking['count']}")

    print("2. QGIS: nach UTM 32N umprojizieren (Meter statt Grad) ...")
    run_algorithm("native:reprojectlayer", {"INPUT": chargers["path"], "TARGET_CRS": "EPSG:25832",
                                            "OUTPUT": p("ladesaeulen_utm.gpkg")})
    run_algorithm("native:reprojectlayer", {"INPUT": parking["path"], "TARGET_CRS": "EPSG:25832",
                                            "OUTPUT": p("parkplaetze_utm.gpkg")})

    print(f"3. QGIS: {buffer_m} m Puffer um jede Ladesäule ...")
    run_algorithm("native:buffer", {"INPUT": p("ladesaeulen_utm.gpkg"), "DISTANCE": buffer_m,
                                    "SEGMENTS": 16, "DISSOLVE": True, "OUTPUT": p("versorgt_utm.gpkg")})

    print("4. QGIS: Parkplätze außerhalb des Puffers finden ...")
    run_algorithm("native:extractbylocation", {"INPUT": p("parkplaetze_utm.gpkg"), "PREDICATE": [2],
                                               "INTERSECT": p("versorgt_utm.gpkg"),
                                               "OUTPUT": p("kandidaten_utm.gpkg")})

    print("5. Zurück nach WGS84 für die Webkarte ...")
    for name in ("versorgt", "kandidaten"):
        run_algorithm("native:reprojectlayer", {"INPUT": p(f"{name}_utm.gpkg"), "TARGET_CRS": "EPSG:4326",
                                                "OUTPUT": p(f"{name}.geojson")})

    with open(p("kandidaten.geojson"), encoding="utf-8") as f:
        n_candidates = len(json.load(f)["features"])
    write_map([p("versorgt.geojson"), p("parkplaetze.geojson"),
               p("ladesaeulen.geojson"), p("kandidaten.geojson")])
    print("-" * 50)
    print(f"Kandidaten (> {buffer_m} m von Ladesäule): {n_candidates}")
    print(f"Karte: {p('karte.html')}")


MAP_COLORS = ["#2a7de1", "#969696", "#00aa50", "#e62828", "#f59e0b", "#8b5cf6", "#0d9488"]


def write_map(geojson_paths, path=None):
    """Leaflet-Karte (HTML) mit den angegebenen GeoJSON-Layern (WGS84). Reihenfolge = Zeichenreihenfolge."""
    path = path or out_path("karte.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(map_html(geojson_paths))
    return path


def map_html(geojson_paths):
    """HTML-Text der Karte (auch für die Ergebnisse-Seite in Streamlit)."""
    layers = []
    for i, path in enumerate(geojson_paths):
        with open(path, encoding="utf-8") as f:
            layers.append({"name": os.path.splitext(os.path.basename(path))[0],
                           "color": MAP_COLORS[i % len(MAP_COLORS)], "data": json.load(f)})
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>Geo-Agent Karte</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>html,body,#map{{height:100%;margin:0}}</style></head><body><div id="map"></div><script>
const layers = {json.dumps(layers)};
const map = L.map('map');
L.tileLayer('https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',{{attribution:'© OpenStreetMap'}}).addTo(map);
const ctl = {{}}, all = L.featureGroup();
layers.forEach((l, i) => {{
  // Objekte können eigene Darstellung mitbringen: properties._style (Leaflet-Stil) und _popup (HTML)
  const own = f => (f.properties || {{}})._style || {{}};
  const g = L.geoJSON(l.data, {{
    style: f => f.geometry.type === 'Point' ? {{}} :
      Object.assign({{color: l.color, fillColor: l.color, fillOpacity: 0.2, weight: 2}}, own(f)),
    pointToLayer: (f, ll) => L.circleMarker(ll,
      Object.assign({{radius: 4 + i, color: 'white', weight: 1, fillColor: l.color, fillOpacity: 1}}, own(f))),
    onEachFeature: (f, lyr) => lyr.bindPopup((f.properties || {{}})._popup || f.properties.name || '(ohne Name)'),
  }}).addTo(map);
  ctl[`<span style="color:${{l.color}}">●</span> ${{l.name}}`] = g;
  g.addTo(all);
}});
// Auf alle Ebenen zoomen. Ist die Karte beim Laden unsichtbar (z.B. in einem Streamlit-Tab), hat sie Größe 0:
// dann neu zoomen, sobald sie sichtbar wird.
const fit = () => {{ map.invalidateSize();
  all.getBounds().isValid() ? map.fitBounds(all.getBounds()) : map.setView([49.87, 8.65], 13); }};
fit();
let lastW = document.getElementById('map').clientWidth;
window.addEventListener('resize', () => {{
  const w = document.getElementById('map').clientWidth;
  w > 0 && lastW === 0 ? fit() : map.invalidateSize();
  lastW = w;
}});
L.control.layers(null, ctl, {{collapsed: false}}).addTo(map);
</script></body></html>"""


if __name__ == "__main__":
    demo()
