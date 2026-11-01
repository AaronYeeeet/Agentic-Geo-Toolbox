"""
QGIS-Demo: "Wo kann ich neue Ladesäulen bauen?" (Darmstadt, rund um TU / Fraunhofer IGD)

So startest du es:
  QGIS öffnen -> Erweiterungen -> Python-Konsole -> "Editor anzeigen" -> diese Datei öffnen -> Ausführen (grüner Pfeil)

Was passiert:
  1. OpenStreetMap als Hintergrundkarte laden
  2. Ladesäulen + Parkplätze live von OpenStreetMap (Overpass API) holen
  3. QGIS-Processing-Werkzeuge ausführen:
       - Umprojizieren nach UTM 32N (Meter statt Grad)
       - 400 m Puffer um jede Ladesäule (= "versorgter Bereich")
       - Parkplätze AUSSERHALB dieses Bereichs finden -> Kandidaten für neue Ladesäulen
  4. Layer einfärben, beschriften, hinzoomen
  5. Karte als PNG speichern
"""
import json
import os
import tempfile
import time
import urllib.parse
import urllib.request

import processing
from qgis.core import (
    QgsApplication, QgsCoordinateReferenceSystem, QgsCoordinateTransform,
    QgsFillSymbol, QgsMarkerSymbol, QgsPalLayerSettings, QgsProject,
    QgsRasterLayer, QgsRectangle, QgsTextFormat, QgsVectorLayer,
    QgsVectorLayerSimpleLabeling,
)
from qgis.PyQt.QtGui import QColor
from qgis.utils import iface

# Gebiet: south, west, north, east (Darmstadt Innenstadt + Lichtwiese)
BBOX = (49.860, 8.630, 49.885, 8.680)
BUFFER_M = 400
OUT = os.path.join(tempfile.gettempdir(), "qgis_demo")
os.makedirs(OUT, exist_ok=True)
project = QgsProject.instance()


# ---------- 1. Daten von OpenStreetMap holen ----------
def overpass_to_geojson(tag_filter, path):
    s, w, n, e = BBOX
    query = f"""[out:json][timeout:60];
    (node[{tag_filter}]({s},{w},{n},{e});
     way[{tag_filter}]({s},{w},{n},{e}););
    out center tags;"""
    # Overpass-Server sind oft überlastet (502/504) -> mehrere Server nacheinander probieren
    servers = [
        "https://overpass-api.de/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter",
        "https://overpass.private.coffee/api/interpreter",
        "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    ]
    osm, last_error = None, None
    for attempt in range(2):
        for url in servers:
            try:
                req = urllib.request.Request(
                    url,
                    data=urllib.parse.urlencode({"data": query}).encode(),
                    headers={"User-Agent": "uni-qgis-prototype"},
                )
                with urllib.request.urlopen(req, timeout=90) as r:
                    osm = json.load(r)
                break
            except Exception as err:
                last_error = err
                print(f"  {url} nicht erreichbar ({err}), versuche nächsten Server ...")
        if osm is not None:
            break
        time.sleep(5)
    if osm is None:
        raise RuntimeError(f"Kein Overpass-Server erreichbar: {last_error}")

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
            "properties": {
                "osm_id": el["id"],
                "name": tags.get("name", ""),
                "operator": tags.get("operator", ""),
                "capacity": tags.get("capacity", ""),
            },
        })
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": features}, f)
    return path


print("Lade Daten von OpenStreetMap ...")
chargers_path = overpass_to_geojson('"amenity"="charging_station"', os.path.join(OUT, "chargers.geojson"))
parking_path = overpass_to_geojson('"amenity"="parking"', os.path.join(OUT, "parking.geojson"))

# ---------- 2. Layer in QGIS laden ----------
project.clear()
project.setCrs(QgsCoordinateReferenceSystem("EPSG:3857"))

basemap = QgsRasterLayer(
    "type=xyz&url=https://tile.openstreetmap.org/{z}/{x}/{y}.png&zmin=0&zmax=19",
    "OpenStreetMap", "wms")
project.addMapLayer(basemap)

chargers = QgsVectorLayer(chargers_path, "Ladesäulen (OSM)", "ogr")
parking = QgsVectorLayer(parking_path, "Parkplätze (OSM)", "ogr")

# ---------- 3. Processing-Werkzeuge (das, was ein Agent aufrufen würde) ----------
print("Führe Processing-Werkzeuge aus ...")
chargers_utm = processing.run("native:reprojectlayer", {
    "INPUT": chargers, "TARGET_CRS": "EPSG:25832", "OUTPUT": "memory:"})["OUTPUT"]
parking_utm = processing.run("native:reprojectlayer", {
    "INPUT": parking, "TARGET_CRS": "EPSG:25832", "OUTPUT": "memory:"})["OUTPUT"]

coverage = processing.run("native:buffer", {
    "INPUT": chargers_utm, "DISTANCE": BUFFER_M, "SEGMENTS": 16,
    "DISSOLVE": True, "OUTPUT": "memory:"})["OUTPUT"]
coverage.setName(f"Versorgt ({BUFFER_M} m um Ladesäule)")

candidates = processing.run("native:extractbylocation", {
    "INPUT": parking_utm, "PREDICATE": [2],  # 2 = disjoint (nicht im Puffer)
    "INTERSECT": coverage, "OUTPUT": "memory:"})["OUTPUT"]
candidates.setName("Kandidaten: neue Ladesäule")

# ---------- 4. Styling ----------
parking.renderer().setSymbol(QgsMarkerSymbol.createSimple(
    {"name": "square", "color": "150,150,150", "size": "2"}))
chargers.renderer().setSymbol(QgsMarkerSymbol.createSimple(
    {"name": "circle", "color": "0,170,80", "size": "3.5", "outline_color": "white"}))
coverage.renderer().setSymbol(QgsFillSymbol.createSimple(
    {"color": "0,170,80,50", "outline_color": "0,120,60", "outline_width": "0.4"}))
candidates.renderer().setSymbol(QgsMarkerSymbol.createSimple(
    {"name": "star", "color": "230,40,40", "size": "5", "outline_color": "white"}))

label = QgsPalLayerSettings()
label.fieldName = "name"
fmt = QgsTextFormat()
fmt.setColor(QColor("darkred"))
fmt.setSize(9)
label.setFormat(fmt)
candidates.setLabeling(QgsVectorLayerSimpleLabeling(label))
candidates.setLabelsEnabled(True)

for lyr in (coverage, parking, chargers, candidates):
    project.addMapLayer(lyr)

# ---------- 5. Hinzoomen + Bild exportieren ----------
s, w, n, e = BBOX
to_map = QgsCoordinateTransform(
    QgsCoordinateReferenceSystem("EPSG:4326"), project.crs(), project)
canvas = iface.mapCanvas()
canvas.setExtent(to_map.transformBoundingBox(QgsRectangle(w, s, e, n)))
canvas.refresh()

png = os.path.join(OUT, "ladesaeulen_karte.png")
canvas.mapCanvasRefreshed.connect(lambda: canvas.saveAsImage(png))

print("-" * 50)
print(f"Ladesäulen gefunden:      {chargers.featureCount()}")
print(f"Parkplätze gefunden:      {parking.featureCount()}")
print(f"Kandidaten (>{BUFFER_M} m entfernt): {candidates.featureCount()}")
print(f"Processing-Algorithmen in deinem QGIS: {len(QgsApplication.processingRegistry().algorithms())}")
print(f"Dateien + PNG: {OUT}")
