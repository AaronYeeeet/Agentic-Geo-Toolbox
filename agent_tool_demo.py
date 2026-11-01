"""
Wie ein "Geo-Agent" QGIS als Werkzeug benutzen könnte - ohne QGIS-Oberfläche.

QGIS bringt das Kommandozeilen-Tool `qgis_process` mit. Damit kann jedes Programm
(z. B. ein LLM-Agent) jeden der ~1000 QGIS-Algorithmen aufrufen und bekommt JSON zurück.

Start (normales Python reicht, nur QGIS muss installiert sein):
    python agent_tool_demo.py
"""
import glob
import json
import os
import subprocess
import tempfile
import urllib.parse
import urllib.request

OUT = os.path.join(tempfile.gettempdir(), "qgis_demo")
os.makedirs(OUT, exist_ok=True)


def find_qgis_process():
    hits = glob.glob(r"C:\Program Files\QGIS*\bin\qgis_process-qgis*.bat") + \
        glob.glob(r"C:\OSGeo4W*\bin\qgis_process-qgis*.bat")
    if not hits:
        raise SystemExit("qgis_process nicht gefunden - ist QGIS installiert?")
    return sorted(hits)[-1]


QGIS = find_qgis_process()


def qgis(*args):
    """Ein 'Tool-Call': ruft qgis_process auf und gibt das JSON-Ergebnis zurück."""
    res = subprocess.run([QGIS, "--json", *args], capture_output=True, text=True)
    start = res.stdout.find("{")  # Warnungen vor dem JSON abschneiden
    if start < 0:
        raise RuntimeError(res.stderr or res.stdout)
    return json.loads(res.stdout[start:])


# --- 1. Was kann QGIS? (das wäre die "Tool-Liste" für das LLM) ---
algs = qgis("list")
all_algs = {a_id: a for p in algs["providers"].values() for a_id, a in p["algorithms"].items()}
print(f"QGIS kennt {len(all_algs)} Algorithmen. Anbieter:")
for name, p in algs["providers"].items():
    print(f"  {name:10s} {len(p['algorithms']):4d}  ({p.get('name', '')})")

print("\nBeispiele mit 'buffer' im Namen:")
for a_id in [a for a in all_algs if "buffer" in a][:8]:
    print("  ", a_id)

# --- 2. Daten holen: Ladesäulen in Darmstadt (OSM) ---
query = """[out:json][timeout:60];
node["amenity"="charging_station"](49.860,8.630,49.885,8.680);out;"""
req = urllib.request.Request(
    "https://overpass-api.de/api/interpreter",
    data=urllib.parse.urlencode({"data": query}).encode(),
    headers={"User-Agent": "uni-qgis-prototype"})
osm = json.load(urllib.request.urlopen(req, timeout=90))
gj = {"type": "FeatureCollection", "features": [
    {"type": "Feature", "geometry": {"type": "Point", "coordinates": [e["lon"], e["lat"]]},
     "properties": {"name": e.get("tags", {}).get("name", "")}}
    for e in osm["elements"]]}
src = os.path.join(OUT, "chargers_cli.geojson")
with open(src, "w", encoding="utf-8") as f:
    json.dump(gj, f)
print(f"\n{len(gj['features'])} Ladesäulen geladen -> {src}")

# --- 3. Tool-Calls ausführen: umprojizieren -> puffern -> Fläche berechnen ---
utm = os.path.join(OUT, "chargers_utm.gpkg")
buf = os.path.join(OUT, "coverage_400m.gpkg")
qgis("run", "native:reprojectlayer", "--",
     f"INPUT={src}", "TARGET_CRS=EPSG:25832", f"OUTPUT={utm}")
qgis("run", "native:buffer", "--",
     f"INPUT={utm}", "DISTANCE=400", "DISSOLVE=true", f"OUTPUT={buf}")
stats = qgis("run", "qgis:exportaddgeometrycolumns", "--",
             f"INPUT={buf}", "CALC_METHOD=0", f"OUTPUT={os.path.join(OUT, 'coverage_area.gpkg')}")
print("Puffer fertig:", buf)
print("Ergebnis-JSON vom letzten Tool-Call:", json.dumps(stats.get("results", stats), indent=2)[:500])
print("\nTipp: Die .gpkg-Dateien kannst du per Drag & Drop in QGIS öffnen.")
