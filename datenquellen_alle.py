"""
Gesamtliste der Datenquellen aus den drei Prototyp-Branches mit Schnittmengen. Ohne Streamlit nutzbar.

Gescannt am 02.11.2026 (aller Code, Prompts, Konfiguration und Doku der Branches):
  aaron-proto-datenquellen (enthält aaron-proto)   Katalog datenquellen.py + Skills, Kartenhintergründe, local_osm.py
  origin/lorenz_prototyp (f5f69f1)                 backend/app/agent/tools/*.py, prompts.py, api/upload.py, MapView.jsx
  origin/ritvik-prototype-frontend (e7c943c)       backend/app/sources/registry.yaml (43 Einträge), Mock-Agent, Frontend

Aarons Katalog (datenquellen.QUELLEN) wird live eingelesen: Neue Quellen dort erscheinen hier automatisch als
"nur Aaron". Alles andere steht unten von Hand. Wird eine Katalog-Quelle auch in einem anderen Branch genutzt,
fasst ein Eintrag in ZUSATZ sie über `katalog=` mit der Nutzung dort zusammen.

Die Seite datenquellen_alle_page.py zeigt die Liste an. Exporte wie bei der Doku (MD, HTML, PDF, CSV, JSON) über
EXPORTE, ohne Oberfläche: python datenquellen_alle.py [ordner] [Thema|Schnittmenge]
"""
import csv
import datetime
import html
import io
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time
from itertools import combinations
from urllib.parse import urlparse

import datenquellen as dq
import datenquellen_doku as doku

STAND = "02.11.2026"

BRANCHES = {  # Schlüssel: Kürzel, Person, Branch, Stand, Technik, wie Quellen angebunden sind
    "aaron": {"kurz": "A", "person": "Aaron", "branch": "aaron-proto-datenquellen", "stand": "5cafc16 + lokale Änderungen",
              "technik": "Streamlit + QGIS",
              "text": f"Katalog mit {len(dq.QUELLEN)} freien Quellen hinter **einem** Werkzeug `datenquelle_abfragen`. Dazu OSM "
                      "(Overpass, lokal per Geofabrik), Nominatim, DGM1 Hessen und Kartenhintergründe in den Skills "
                      "(hitze, starkregen, ladesaeulen, traffic_impact). `aaron-proto` ist darin enthalten."},
    "lorenz": {"kurz": "L", "person": "Lorenz", "branch": "lorenz_prototyp", "stand": "f5f69f1, 01.11.2026",
               "technik": "FastAPI + React/MapLibre",
               "text": "Wenige allgemeine Werkzeuge: `fetch_osm` (osmnx/Overpass), `search_open_data` (GovData), "
                       "`load_geodata_from_url`, `wms_capabilities`/`add_wms_layer` und Datei-Upload. "
                       "Bekannter Dienst im Systemprompt: Luftbild Hessen."},
    "ritvik": {"kurz": "R", "person": "Ritvik", "branch": "ritvik-prototype-frontend", "stand": "e7c943c, 01.11.2026",
               "technik": "FastAPI + React/MapLibre",
               "text": "Quellen-Registry `registry.yaml` mit 43 geprüften Einträgen (Lizenz, Abdeckung, CORS) für "
                       "Basiskarten, Luftbilder aller Länder, Gelände, 3D-Gebäude und Suche. Der Agent ist noch ein "
                       "Mock: Er nennt OSM, BNetzA u.a. als Quellen, liefert aber Demo-Daten."},
}

STATUS = {  # Stufe: (Symbol, Name, Erklärung)
    "aktiv": ("✅", "aktiv", "wird im Prototyp tatsächlich abgerufen"),
    "vorbereitet": ("🟡", "vorbereitet", "eingetragen oder geprüft, wird aber noch nicht abgerufen"),
    "simuliert": ("🧪", "nur Demo / geplant", "nur als Quelle von Demo-Daten oder als Plan genannt"),
}

T_OSM = "OpenStreetMap & Ortssuche"
T_KARTE = "Basiskarten"
T_LUFTBILD = "Luftbilder"
T_GELAENDE = "Gelände & 3D"
THEMEN = [T_OSM, T_KARTE, T_LUFTBILD, T_GELAENDE] + dq.KATEGORIEN
THEMA_INFO = {
    **doku.KAT_INFO,
    T_OSM: ("🧭", "OSM-Objekte, Straßennetz und Ortssuche."),
    T_KARTE: ("🗺️", "Hintergrundkarten als Vektor- oder Rasterkacheln, amtliche Karten Hessen."),
    T_LUFTBILD: ("📷", "Luftbilder (DOP) der Länder und Satellitenmosaik."),
    T_GELAENDE: ("⛰️", "Höhenmodelle, Schummerung und 3D-Gebäude."),
    dq.K_FERN: ("🛰️", "Versiegelung, Bäume, Landbedeckung, Vegetation und Oberflächentemperatur aus Satellitendaten."),
    dq.K_KAT: ("🗂️", "Open-Data-Kataloge, beliebige Dateien und Dienste, eigene Dateien per Upload."),
}
THEMA_KATALOG = {"gelaendehoehe": T_GELAENDE}  # Katalog-Quellen, die hier unter einem anderen Thema stehen


def _q(id, name, thema, anbieter, url="", dienst="", aaron=None, lorenz=None, ritvik=None, katalog=()):
    """Ein Eintrag. Nutzung je Branch: Text (= aktiv) oder (Stufe, Text); None = nicht genutzt."""
    nutzung = {}
    for b, v in (("aaron", aaron), ("lorenz", lorenz), ("ritvik", ritvik)):
        if v:
            nutzung[b] = ("aktiv", v) if isinstance(v, str) else v
    return {"id": id, "name": name, "thema": thema, "anbieter": anbieter, "url": url, "dienst": dienst,
            "nutzung": nutzung, "katalog": tuple(katalog)}


GDS = "https://www.gds-srv.hessen.de/cgi-bin/lika-services/"
BKG = "https://sgx.geodatenzentrum.de/"
OFM = "https://tiles.openfreemap.org/styles/"
REG = "Registry `{}`"


def _reg(rid, text, status="aktiv"):
    """Nutzung bei Ritvik mit Verweis auf den Registry-Eintrag."""
    return (status, f"{text} ({REG.format(rid)})")


ZUSATZ = [
    # ---------------------------------------------------------------- OpenStreetMap & Ortssuche
    _q("overpass", "OpenStreetMap-Objekte (Overpass API)", T_OSM, "OpenStreetMap-Mitwirkende, Server FOSSGIS e.V. u.a.",
       "https://wiki.openstreetmap.org/wiki/Overpass_API", "https://overpass-api.de/api/interpreter",
       aaron="`fetch_osm`, `geocode` (Kreuzungen), Straßennetz für `traffic_impact` (osmnx), Gebäude, Grünflächen, "
             "Bäume und Trafostationen in `hitze`, `starkregen`, `ladesaeulen`. 4 Server mit Ausweichen.",
       lorenz="`fetch_osm` über osmnx (Ortsname oder BBox + OSM-Tags), 3 Server mit Ausweichen, Antworten im Cache.",
       ritvik=("simuliert", "Der Mock-Agent zeigt OSM-Parkplätze und -Schulen als Demo-Daten, echte Abfragen sind für "
                            "Iteration 1 geplant. Registry `overpass-fossgis` (Kandidat).")),
    _q("geofabrik", "OSM-Auszug Hessen (Geofabrik, .osm.pbf)", T_OSM, "Geofabrik GmbH (OSM-Daten)",
       "https://download.geofabrik.de/europe/germany/hessen.html",
       "https://download.geofabrik.de/europe/germany/hessen-latest.osm.pbf",
       aaron="`local_osm.py`: lokale Kopie für Darmstadt und Umland, wenn Overpass überlastet ist (OSM-Objekte, "
             "Kreuzungen, Straßennetz, Flächen)."),
    _q("nominatim", "Adresssuche Nominatim (OSM)", T_OSM, "OpenStreetMap Foundation", "https://nominatim.org",
       "https://nominatim.openstreetmap.org/search",
       aaron="`geocode`: Adressen und Orte in Koordinaten (höchstens 1 Anfrage pro Sekunde).",
       lorenz="Indirekt über osmnx, wenn `fetch_osm` einen Ortsnamen bekommt (Ort → Umriss).",
       ritvik=_reg("nominatim-osm", "Geprüft als Backend-Geocoder, wird aber noch nicht aufgerufen; der Mock nutzt "
                                    "einen kleinen lokalen Ortskatalog", "vorbereitet")),
    _q("photon", "Ortssuche Photon (komoot)", T_OSM, "komoot (OSM-Daten)", "https://photon.komoot.io",
       "https://photon.komoot.io/api/",
       ritvik=_reg("photon-komoot", "Suchfeld der Karte mit Vorschlägen beim Tippen; auch die Koordinaten des lokalen "
                                    "Ortskatalogs stammen daher")),

    # ---------------------------------------------------------------- Basiskarten
    _q("osm_kacheln", "OpenStreetMap-Standardkarte (Rasterkacheln)", T_KARTE, "OpenStreetMap Foundation",
       "https://www.openstreetmap.org/copyright", "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
       aaron="Standard-Hintergrund jeder Karte (`make_map`).",
       lorenz="Basiskarte im Frontend (MapLibre)."),
    _q("ofm_liberty", "OpenFreeMap Liberty (OSM-Vektorkarte mit 3D-Gebäuden)", T_KARTE, "OpenFreeMap",
       "https://openfreemap.org", OFM + "liberty",
       ritvik=_reg("openfreemap-liberty", "Standard-Basiskarte „OSM“ mit 2.5D-Gebäuden, Beschriftung über dem Luftbild")),
    _q("ofm_bright", "OpenFreeMap Bright (OSM-Vektorkarte)", T_KARTE, "OpenFreeMap", "https://openfreemap.org",
       OFM + "bright", ritvik=_reg("openfreemap-bright", "Ersatz-Stil, wenn eine Basiskarte nicht lädt")),
    _q("ofm_positron", "OpenFreeMap Positron (helle OSM-Vektorkarte)", T_KARTE, "OpenFreeMap", "https://openfreemap.org",
       OFM + "positron", ritvik=_reg("openfreemap-positron", "Ersatz-Stil, wenn eine Basiskarte nicht lädt")),
    _q("bm_farbe", "basemap.de Web Vektor – Farbe", T_KARTE, "BKG / AdV (basemap.de)", "https://basemap.de",
       BKG + "gdz_basemapde_vektor/styles/bm_web_col.json",
       ritvik=_reg("basemapde-colour", "Basiskarte „Amtlich“, im Code fest eingebunden (in der Registry noch Kandidat)")),
    _q("bm_grau", "basemap.de Web Vektor – Grau", T_KARTE, "BKG / AdV (basemap.de)", "https://basemap.de",
       BKG + "gdz_basemapde_vektor/styles/bm_web_gry.json",
       ritvik=_reg("basemapde-grey", "Basiskarte „Hell“, im Code fest eingebunden (in der Registry noch Kandidat)")),
    _q("bm_relief", "basemap.de Web Vektor – Relief", T_KARTE, "BKG / AdV (basemap.de)", "https://basemap.de",
       BKG + "gdz_basemapde_vektor/styles/bm_web_top.json",
       ritvik=_reg("basemapde-relief", "Basiskarte „Relief“, im Code fest eingebunden (in der Registry noch Kandidat)")),
    _q("bm_nacht", "basemap.de Web Vektor – Nachtstil (Beta)", T_KARTE, "BKG / AdV (basemap.de)", "https://basemap.de",
       "https://basemap.de/data/produkte/web_vektor/styles/bm_web_drk.json",
       ritvik=_reg("basemapde-night-beta", "Kandidat, nicht eingebunden", "vorbereitet")),
    _q("bm_binaer", "basemap.de Web Vektor – Binärstil (Beta)", T_KARTE, "BKG / AdV (basemap.de)", "https://basemap.de",
       "https://basemap.de/data/produkte/web_vektor/styles/bm_web_bin.json",
       ritvik=_reg("basemapde-binary-beta", "Kandidat, nicht eingebunden", "vorbereitet")),
    _q("bm_welt", "basemap.world Web Vektor – Farbe", T_KARTE, "BKG (basemap.world)", "https://basemap.de",
       BKG + "gdz_basemapworld_vektor/styles/bm_web_wld_col.json",
       ritvik=_reg("basemapworld-colour", "Kandidat für eine Weltkarte, nicht eingebunden", "vorbereitet")),
    _q("bm_raster_wms", "basemap.de Web Raster (WMS)", T_KARTE, "BKG / AdV (basemap.de)", "https://basemap.de",
       BKG + "wms_basemapde",
       ritvik=_reg("basemapde-web-raster-wms", "Kandidat als Raster-Ersatz, nicht eingebunden", "vorbereitet")),
    _q("bm_raster_wmts", "basemap.de Web Raster (WMTS-Kacheln)", T_KARTE, "BKG / AdV (basemap.de)", "https://basemap.de",
       BKG + "wmts_basemapde/tile/1.0.0/de_basemapde_web_raster_grau/default/GLOBAL_WEBMERCATOR/{z}/{y}/{x}.png",
       aaron="Hintergrund „basemap.de (grau)“ in jeder Karte.",
       ritvik=_reg("basemapde-web-raster-wmts-xyz", "Kandidat (farbig/grau) als Raster-Ersatz, nicht eingebunden",
                   "vorbereitet")),
    _q("hessen_alk", "Liegenschaftskarte Hessen (ALKIS)", T_KARTE, "HVBG Hessen", "https://gds.hessen.de",
       GDS + "ogc-free-maps.ows  (Ebene he_alk)",
       aaron="Katalog `karte_hessen` (ebene liegenschaftskarte) und Hintergrund in jeder Karte.",
       ritvik=_reg("hessen-alk", "Overlay „Kataster“, ab Zoomstufe 16"), katalog=["karte_hessen"]),
    _q("hessen_dtk", "Topografische Karte Hessen (DTK)", T_KARTE, "HVBG Hessen", "https://gds.hessen.de",
       GDS + "ogc-free-maps.ows  (Ebene he_dtk25 / he_dtk)",
       aaron="Katalog `karte_hessen` (ebene topokarte).",
       ritvik=_reg("hessen-dtk", "Overlay „Topografie“, ab Zoomstufe 13"), katalog=["karte_hessen"]),
    _q("hessen_uek", "Übersichtskarte Hessen (ÜK)", T_KARTE, "HVBG Hessen", "https://gds.hessen.de",
       GDS + "ogc-free-maps.ows  (Ebene he_uek)",
       ritvik=_reg("hessen-uek", "Overlay „Übersicht“ für kleine Maßstäbe")),

    # ---------------------------------------------------------------- Luftbilder
    _q("hessen_dop", "Luftbild Hessen (DOP 20 cm)", T_LUFTBILD, "HVBG Hessen", "https://gds.hessen.de",
       GDS + "ogc-free-images.ows  (Ebene he_dop_rgb / he_dop20_rgb)",
       aaron="Katalog `karte_hessen` (ebene luftbild) und Hintergrund „Luftbild Hessen 20 cm“ in jeder Karte.",
       lorenz="Im Systemprompt als bekannter WMS für `add_wms_layer` (he_dop20_rgb), im Smoke-Test geprüft.",
       ritvik=_reg("hessen-dop20", "Luftbild-Basiskarte für Hessen"), katalog=["karte_hessen"]),
    # weitere Länder-Luftbilder kommen aus _DOP (unten)
    _q("eox_2025", "Sentinel-2 cloudless 2025 (EOX, Satellitenmosaik)", T_LUFTBILD, "EOX IT Services",
       "https://cloudless.eox.at", "https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-2025_3857/default/g/{z}/{y}/{x}.jpg",
       ritvik=_reg("eox-s2cloudless-2025", "grobes Luftbild außerhalb der Länder-Luftbilder")),
    _q("eox_2016", "Sentinel-2 cloudless 2016 (EOX)", T_LUFTBILD, "EOX IT Services", "https://cloudless.eox.at",
       "https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless_3857/default/g/{z}/{y}/{x}.jpg",
       ritvik=_reg("eox-s2cloudless-2016", "Kandidat, ältere freie Version", "vorbereitet")),

    # ---------------------------------------------------------------- Gelände & 3D
    _q("dgm1_hessen", "DGM1 Hessen (Laserscan-Geländemodell, WCS)", T_GELAENDE, "HVBG Hessen", "https://gds.hessen.de",
       "https://inspire-hessen.de/raster/dgm1/ows",
       aaron="`starkregen`: Geländehöhe in 2 m, gemittelt auf 4 m, für Fließwege und Senken."),
    _q("aws_terrarium", "AWS-Geländekacheln (Terrarium, ca. 30 m)", T_GELAENDE, "Mapzen/Tilezen über AWS Open Data",
       "https://registry.opendata.aws/terrain-tiles/", "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png",
       aaron="`starkregen`: grobes Höhenmodell als Ersatz, wenn DGM1 nicht erreichbar ist.",
       ritvik=_reg("aws-terrain-terrarium", "3D-Gelände als Ersatz für Mapterhorn")),
    _q("mapterhorn", "Mapterhorn-Geländekacheln (1 m in Deutschland)", T_GELAENDE, "Mapterhorn", "https://mapterhorn.com",
       "https://tiles.mapterhorn.com/{z}/{x}/{y}.webp",
       ritvik=_reg("mapterhorn-terrain", "3D-Gelände und Schummerung der Karte")),
    _q("mapterhorn_pmtiles", "Mapterhorn-Geländekacheln (PMTiles-Archiv)", T_GELAENDE, "Mapterhorn",
       "https://mapterhorn.com", "https://download.mapterhorn.com/planet.pmtiles",
       ritvik=_reg("mapterhorn-terrain-pmtiles", "Kandidat, nicht eingebunden", "vorbereitet")),
    _q("bm_schummerung", "basemap.de Schummerung (WMS)", T_GELAENDE, "BKG / AdV (basemap.de)", "https://basemap.de",
       BKG + "wms_basemapde_schummerung",
       ritvik=_reg("basemapde-schummerung-wms", "Kandidat als Relief-Overlay, nicht eingebunden", "vorbereitet")),
    _q("bm_dgm5", "basemap.de 3D Gelände DGM5", T_GELAENDE, "BKG / AdV (basemap.de 3D, Beta)", "https://basemap.de",
       BKG + "gdz_basemapde_3d_gelaende/dgm5_3857_rgb.json",
       ritvik=_reg("basemapde-terrain-dgm5-rgb", "Kandidat, nicht eingebunden", "vorbereitet")),
    _q("bm_lod2", "basemap.de 3D-Gebäude LoD2", T_GELAENDE, "BKG / AdV (basemap.de 3D, Beta)", "https://basemap.de",
       BKG + "gdz_basemapde_3d_gebaeude/lod2_4326_null.json",
       ritvik=_reg("basemapde-3d-buildings-lod2-3857", "3D-Gebäude in der Karte; der Code lädt die Variante "
                                                       "lod2_4326_null.json")),
    _q("bm_lod2_dgm5", "basemap.de 3D-Gebäude LoD2 auf DGM5-Gelände", T_GELAENDE, "BKG / AdV (basemap.de 3D, Beta)",
       "https://basemap.de", BKG + "gdz_basemapde_3d_gebaeude/lod2_4326_dgm5.json",
       ritvik=_reg("basemapde-3d-buildings-lod2-4326-dgm5", "für später vorgemerkt", "vorbereitet")),

    # ---------------------------------------------------------------- Kataloge, beliebige Dienste, eigene Dateien
    _q("govdata", "GovData-Katalog (CKAN, mit Open Data Hessen)", dq.K_KAT, "GovData (Bund, Länder, Kommunen)",
       "https://www.govdata.de", "https://www.govdata.de/ckan/api/3/action/package_search",
       aaron="Katalog `govdata`: Datensätze mit Download-Links suchen.",
       lorenz="`search_open_data`: Suche, standardmäßig auf Hessen gefiltert; Treffer weiter mit `load_geodata_from_url`.",
       ritvik=("simuliert", "Nur als geplante Datensatzsuche (Iteration 1) in der Antwort des Mock-Agenten genannt."),
       katalog=["govdata"]),
    _q("gdi_de", "GDI-DE Geodatenkatalog", dq.K_KAT, "Koordinierungsstelle GDI-DE (BKG)", "https://www.geoportal.de",
       ritvik=("simuliert", "Nur als geplante Datensatzsuche (Iteration 1) in der Antwort des Mock-Agenten genannt.")),
    _q("datei_url", "Beliebige Geodaten-Datei per URL", dq.K_KAT, "je nach Quelle",
       aaron="Katalog `datei_laden` (CSV, GeoJSON, ZIP mit Shapefile).",
       lorenz="`load_geodata_from_url`: GeoJSON, GML, GeoPackage, Shapefile-ZIP (GeoPandas/GDAL).",
       katalog=["datei_laden"]),
    _q("wfs_beliebig", "Beliebiger WFS-Dienst", dq.K_KAT, "je nach Dienst",
       aaron="Katalog `wfs_abfrage` (über ogr2ogr aus QGIS).",
       lorenz="`load_geodata_from_url` mit einer WFS-GetFeature-Adresse.", katalog=["wfs_abfrage"]),
    _q("wms_beliebig", "Beliebiger WMS-Dienst", dq.K_KAT, "je nach Dienst",
       aaron="Katalog `wms_abfrage`: Wert am Punkt (GetFeatureInfo).",
       lorenz="`wms_capabilities` (Ebenen auflisten) und `add_wms_layer` (als Rasterebene auf die Karte).",
       katalog=["wms_abfrage"]),
    _q("upload", "Eigene Dateien (Upload)", dq.K_KAT, "Nutzerin / Nutzer",
       lorenz="Upload-Knopf: GeoJSON, GeoPackage, Shapefile-ZIP, KML werden zur Ebene und dem Agenten gemeldet.",
       ritvik="Drag & Drop auf die Karte: GeoJSON, CSV mit Koordinaten, KML, GPX (bis 10 MB, nur im Browser)."),

    # ---------------------------------------------------------------- Bevölkerung, Energie, Landbedeckung
    _q("bnetza_ladesaeulen", "Ladesäulenregister (BNetzA)", dq.K_BEV, "Bundesnetzagentur",
       "https://www.bundesnetzagentur.de/ladeinfrastruktur",
       "https://data.bundesnetzagentur.de/…/E-Mobilitaet/Ladesaeulenregister_BNetzA_….csv",
       aaron="Katalog `ladesaeulen_register` und Bestand in der Ladesäulen-Analyse `ladesaeulen` (CSV einmal geladen).",
       ritvik=("simuliert", "Der Mock-Agent nennt es als Quelle der Ladesäulen-Antwort, die Zahlen sind Demo-Daten."),
       katalog=["ladesaeulen_register"]),
    _q("zensus", "Zensus 2022 – 100-m-Gitter (Destatis)", dq.K_BEV, "Statistisches Bundesamt (Destatis)",
       "https://www.zensus2022.de", "https://www.destatis.de/static/DE/zensus/gitterdaten/",
       aaron="Katalog `zensus2022` und Bedarf in `ladesaeulen` (Einwohner, Gebäude nach Wohnungen, Eigentümerquote).",
       katalog=["zensus2022"]),
    _q("corine", "CORINE Land Cover (Copernicus)", dq.K_FERN, "EEA / Copernicus Land Monitoring Service",
       "https://land.copernicus.eu/en/products/corine-land-cover",
       ritvik=("simuliert", "In der Demo-Antwort zur Fläche als Quelle genannt; der Grünanteil ist simuliert.")),
]

_DOP = [  # Länder-Luftbilder aus Ritviks Registry: (Registry-ID, Name, Anbieter, Webseite, Dienst, Stufe, Anmerkung)
    ("nrw-dop", "NRW (DOP10, True-Orthophoto)", "Geobasis NRW", "https://www.bezreg-koeln.nrw.de/geobasis-nrw",
     "https://www.wms.nrw.de/geobasis/wms_nw_dop", "aktiv", ""),
    ("bayern-dop20", "Bayern (DOP20)", "LDBV Bayern", "https://geodaten.bayern.de/opengeodata/",
     "https://geoservices.bayern.de/od/wms/dop/v1/dop20", "aktiv", ""),
    ("bayern-dop40", "Bayern (DOP40)", "LDBV Bayern", "https://geodaten.bayern.de/opengeodata/",
     "https://geoservices.bayern.de/od/wms/dop/v1/dop40", "vorbereitet", "geprüft, als Alternative zu DOP20 vorgemerkt"),
    ("baden-wuerttemberg-dop20", "Baden-Württemberg (DOP20)", "LGL Baden-Württemberg", "https://www.lgl-bw.de",
     "https://owsproxy.lgl-bw.de/owsproxy/ows/WMS_LGL-BW_ATKIS_DOP_20_C", "aktiv", ""),
    ("niedersachsen-dop20", "Niedersachsen (DOP20)", "LGLN Niedersachsen", "https://www.lgln.niedersachsen.de",
     "https://opendata.lgln.niedersachsen.de/doorman/noauth/dop_wms", "aktiv", ""),
    ("sachsen-dop20", "Sachsen (DOP20)", "GeoSN Sachsen", "https://www.geodaten.sachsen.de",
     "https://geodienste.sachsen.de/wms_geosn_dop-rgb/guest", "aktiv", ""),
    ("brandenburg-dop20c", "Brandenburg und Berlin (DOP20c)", "LGB Brandenburg", "https://geobasis-bb.de",
     "https://isk.geobasis-bb.de/mapproxy/dop20c/service/wms", "aktiv", ""),
    ("berlin-truedop-2024", "Berlin (TrueOrthophotos 2024)", "Geoportal Berlin", "https://gdi.berlin.de",
     "https://gdi.berlin.de/services/wms/truedop_2024", "aktiv", ""),
    ("hamburg-dop20-unbelaubt", "Hamburg (DOP20 unbelaubt)", "LGV Hamburg", "https://www.hamburg.de/geoinfo/",
     "https://geodienste.hamburg.de/wms_dop_zeitreihe_unbelaubt", "vorbereitet", "Kandidat, noch nicht geprüft"),
    ("thueringen-dop20", "Thüringen (DOP20)", "TLBG Thüringen", "https://www.geoportal-th.de",
     "https://www.geoproxy.geoportal-th.de/geoproxy/services/DOP", "aktiv", ""),
    ("rheinland-pfalz-dop20", "Rheinland-Pfalz (DOP20)", "LVermGeo Rheinland-Pfalz", "https://lvermgeo.rlp.de",
     "https://geo4.service24.rlp.de/wms/rp_dop20.fcgi", "aktiv", ""),
    ("saarland-dop20", "Saarland (DOP20)", "LVGL Saarland", "https://geoportal.saarland.de",
     "https://geoportal.saarland.de/freewms/truedop", "aktiv", ""),
    ("sachsen-anhalt-dop20", "Sachsen-Anhalt (DOP20)", "LVermGeo Sachsen-Anhalt", "https://www.lvermgeo.sachsen-anhalt.de",
     "https://www.geodatenportal.sachsen-anhalt.de/wss/service/ST_LVermGeo_DOP_WMS_OpenData/guest", "vorbereitet",
     "funktioniert, aber ohne CORS für den Browser (bräuchte einen Proxy)"),
    ("schleswig-holstein-dop20", "Schleswig-Holstein (DOP20)", "LVermGeo Schleswig-Holstein",
     "https://www.schleswig-holstein.de/DE/landesregierung/ministerien-behoerden/LVERMGEOSH/",
     "https://dienste.gdi-sh.de/WMS_SH_DOP20col_OpenGBD", "vorbereitet",
     "funktioniert, aber ohne CORS für den Browser (bräuchte einen Proxy)"),
    ("mecklenburg-vorpommern-dop20", "Mecklenburg-Vorpommern (DOP20)", "LAiV Mecklenburg-Vorpommern",
     "https://www.geoportal-mv.de", "https://www.geodaten-mv.de/dienste/adv_dop", "aktiv", ""),
    ("bremen-dop10", "Bremen und Bremerhaven (DOP10, 2025)", "GeoInformation Bremen", "https://www.geo.bremen.de",
     "https://geodienste.bremen.de/wms_dop_lb", "aktiv", ""),
]
ZUSATZ += [_q(rid.replace("-", "_"), f"Luftbild {name}", T_LUFTBILD, anbieter, url, dienst,
              ritvik=_reg(rid, text or "Luftbild-Basiskarte, geprüft", stufe))
           for rid, name, anbieter, url, dienst, stufe, text in _DOP]


def zeilen():
    """Alle Einträge: ZUSATZ plus jede Katalog-Quelle von Aaron, die dort nicht schon zusammengefasst ist."""
    erfasst = {k for z in ZUSATZ for k in z["katalog"]}
    rows = list(ZUSATZ)
    for qid, q in dq.QUELLEN.items():
        if qid in erfasst:
            continue
        endp = doku.technik(qid)[1]
        rows.append(_q(qid, q["name"], THEMA_KATALOG.get(qid, q["kategorie"]), doku.anbieter_kurz(q["anbieter"]),
                       q["url"], endp[0] if endp else "", aaron=f"Katalog `{qid}`", katalog=[qid]))
    reihenfolge = {t: i for i, t in enumerate(THEMEN)}
    return sorted(rows, key=lambda r: reihenfolge.get(r["thema"], 99))


def genutzt(row, nur_aktiv=False):
    """Branches, die die Quelle nutzen (in der Reihenfolge von BRANCHES)."""
    return tuple(b for b in BRANCHES if b in row["nutzung"] and (not nur_aktiv or row["nutzung"][b][0] == "aktiv"))


def bereiche():
    """Alle 7 Bereiche des Venn-Diagramms, von allen drei bis zu je einem Branch."""
    keys = list(BRANCHES)
    return [c for n in (3, 2, 1) for c in combinations(keys, n)]


def bereich_name(combo):
    if len(combo) == len(BRANCHES):
        return "in allen drei"
    namen = [BRANCHES[b]["person"] for b in combo]
    return "nur " + " + ".join(namen)


def schnittmengen(rows, nur_aktiv=False):
    """{Branch-Kombination: [Einträge]} für genau diese Kombination (ohne Einträge, die keiner nutzt)."""
    out = {c: [] for c in bereiche()}
    for r in rows:
        c = genutzt(r, nur_aktiv)
        if c:
            out[c].append(r)
    return out


def bereich_titel(combo):
    n = bereich_name(combo)
    return n[0].upper() + n[1:]


def gruppen(gruppierung, rows, nur_aktiv=False):
    """[(Titel, Symbol, Info, Einträge)] nach Thema oder Schnittmenge, leere Gruppen weggelassen."""
    if gruppierung == "Schnittmenge":
        out = [(bereich_titel(c), "🔀" if len(c) > 1 else "👤", None,
                [r for r in rows if genutzt(r, nur_aktiv) == c]) for c in bereiche()]
    else:
        out = [(t, THEMA_INFO[t][0], THEMA_INFO[t][1], [r for r in rows if r["thema"] == t]) for t in THEMEN]
    return [g for g in out if g[3]]


FARBEN = {"aaron": "#3b82c4", "lorenz": "#f59e0b", "ritvik": "#22c55e"}


def venn_svg(sm, max_breite=380):
    """Drei Kreise mit der Anzahl je Bereich (SVG; Zahlen in Textfarbe, passt zu hell und dunkel)."""
    a, l, r = BRANCHES
    pos = {(a,): (88, 112), (l,): (272, 112), (r,): (180, 262), (a, l): (180, 92), (a, r): (124, 196),
           (l, r): (236, 196), (a, l, r): (180, 152)}
    kreise = {a: (132, 128), l: (228, 128), r: (180, 210)}
    namen = {a: (60, 24, "start"), l: (300, 24, "end"), r: (180, 330, "middle")}
    svg = [f'<svg viewBox="0 0 360 340" width="100%" style="max-width:{max_breite}px;display:block;margin:auto" '
           'xmlns="http://www.w3.org/2000/svg" font-family="sans-serif">']
    for b, (cx, cy) in kreise.items():
        svg.append(f'<circle cx="{cx}" cy="{cy}" r="96" fill="{FARBEN[b]}" fill-opacity="0.2" '
                   f'stroke="{FARBEN[b]}" stroke-width="2"/>')
    for b, (x, y, anker) in namen.items():
        n = sum(len(v) for c, v in sm.items() if b in c)
        svg.append(f'<text x="{x}" y="{y}" text-anchor="{anker}" font-size="15" font-weight="600" '
                   f'fill="{FARBEN[b]}">{BRANCHES[b]["person"]} ({n})</text>')
    for c, (x, y) in pos.items():
        n = len(sm.get(c, []))
        gross = len(c) == 3
        svg.append(f'<text x="{x}" y="{y}" text-anchor="middle" dominant-baseline="middle" fill="currentColor" '
                   f'font-size="{22 if gross else 18}" font-weight="{700 if gross or n else 400}" '
                   f'opacity="{1 if n else 0.45}">{n}</text>')
    return "".join(svg) + "</svg>"


# =====================================================================================================
# Exporte. Gleiches Format wie die Doku von Aarons Quellen (datenquellen_doku.py), nur die Quellen selbst
# (ohne Vergleich der Prototypen), immer nach Thema gruppiert:
#   1. alle Kategorien als Tabellen nacheinander
#   2. je Kategorie die Quellen mit kurzen Infos
# =====================================================================================================
TITEL = "Datenquellen aller Prototypen"
GRUPPIERUNGEN = ["Thema", "Schnittmenge"]  # nur für die Seite

BESCHREIBUNG = {  # Kurzbeschreibung der Quellen, die nicht (nur) aus Aarons Katalog kommen
    "overpass": "OSM-Objekte (Gebäude, Straßen, Grünflächen, Einrichtungen …) nach Tags für einen Ort oder Ausschnitt.",
    "geofabrik": "Kompletter OSM-Datenstand von Hessen als Datei, täglich aktualisiert; lokal ohne Internet nutzbar.",
    "nominatim": "Wandelt Adressen und Ortsnamen in Koordinaten um (und zurück).",
    "photon": "Ortssuche mit Vorschlägen beim Tippen, auf Basis von OSM-Daten.",
    "osm_kacheln": "Die bekannte OpenStreetMap-Karte als Rasterkacheln, Hintergrund für Karten.",
    "ofm_liberty": "Freie OSM-Vektorkarte ohne Schlüssel und ohne Limits, mit 3D-Gebäuden.",
    "ofm_bright": "Kräftiger Kartenstil von OpenFreeMap (OSM-Vektorkacheln).",
    "ofm_positron": "Heller, zurückhaltender Kartenstil von OpenFreeMap (OSM-Vektorkacheln).",
    "bm_farbe": "Amtliche Grundkarte Deutschlands (AdV) als Vektorkacheln, farbig.",
    "bm_grau": "Amtliche Grundkarte Deutschlands als Vektorkacheln, in Grautönen.",
    "bm_relief": "Amtliche Grundkarte Deutschlands mit Schummerung und Höhenlinien.",
    "bm_nacht": "Amtliche Grundkarte Deutschlands, dunkler Stil (Beta).",
    "bm_binaer": "Amtliche Grundkarte Deutschlands, schwarz-weißer Stil (Beta).",
    "bm_welt": "Weltkarte des BKG im Stil von basemap.de, Vektorkacheln.",
    "bm_raster_wms": "Amtliche Grundkarte Deutschlands als Rasterbild über WMS.",
    "bm_raster_wmts": "Amtliche Grundkarte Deutschlands als Rasterkacheln (WMTS), farbig oder grau.",
    "hessen_alk": "Flurstücke und Gebäude aus dem amtlichen Liegenschaftskataster Hessen (ALKIS) als WMS.",
    "hessen_dtk": "Topografische Karte Hessen 1:25.000 bis 1:100.000 als WMS.",
    "hessen_uek": "Übersichtskarte Hessen für kleine Maßstäbe als WMS.",
    "hessen_dop": "Luftbilder Hessen mit 20 cm Bodenauflösung als WMS.",
    "eox_2025": "Wolkenfreies Satellitenbildmosaik aus Sentinel-2 (10 m), weltweit, Stand 2025.",
    "eox_2016": "Wolkenfreies Sentinel-2-Mosaik, ältere Version von 2016 mit freier Lizenz.",
    "dgm1_hessen": "Digitales Geländemodell Hessen aus Laserscan, 1-m-Raster, abrufbar über WCS.",
    "aws_terrarium": "Weltweite Geländehöhen als Kacheln (ca. 30 m), Terrarium-Kodierung.",
    "mapterhorn": "Geländehöhen als Kacheln, in Deutschland bis 1 m, für 3D-Gelände und Schummerung.",
    "mapterhorn_pmtiles": "Dieselben Mapterhorn-Höhendaten als PMTiles-Archiv zum Herunterladen.",
    "bm_schummerung": "Schattiertes Relief Deutschlands als WMS-Overlay.",
    "bm_dgm5": "Geländehöhen Deutschland (DGM5) als RGB-Höhenkacheln (Beta).",
    "bm_lod2": "3D-Gebäudemodelle (LoD2) für ganz Deutschland als 3D Tiles (Beta).",
    "bm_lod2_dgm5": "LoD2-Gebäude auf DGM5-Geländehöhe als 3D Tiles (Beta).",
    "gdi_de": "Bundesweiter Katalog amtlicher Geodaten und Geodienste (Geoportal.de).",
    "upload": "Eigene Geodaten der Nutzerin oder des Nutzers (GeoJSON, GeoPackage, Shapefile, KML, GPX, CSV).",
    "corine": "Europäische Landbedeckung in 44 Klassen (Mindestfläche 25 ha), alle 6 Jahre neu.",
}
DOP_TEXT = "Luftbilder (digitale Orthophotos) des Landes als WMS."


def eintrag(r):
    """Alle Export-Felder einer Quelle. Für Quellen aus Aarons Katalog kommen Beschreibung, Stichworte, Lizenz,
    Art, Dienst-Adressen und Parameter aus der Doku (datenquellen_doku.eintrag)."""
    kat = doku.eintrag(r["katalog"][0]) if len(r["katalog"]) == 1 and r["id"] not in BESCHREIBUNG else None
    kurz = BESCHREIBUNG.get(r["id"]) or (kat["kurzbeschreibung"] if kat else "") or \
        (DOP_TEXT if r["thema"] == T_LUFTBILD else "")
    return {
        "id": r["id"], "name": r["name"], "thema": r["thema"], "kurzbeschreibung": kurz,
        "stichworte": kat["stichworte"] if kat else [],
        "beschreibung": kat["beschreibung"] if kat else "",
        "art": kat["art"] if kat else "", "anbindung": kat["anbindung"] if kat else "",
        "anbieter": kat["anbieter"] if kat else r["anbieter"], "lizenz": kat["lizenz"] if kat else "",
        "webseite": r["url"] or None,
        "dienst_adressen": kat["dienst_adressen"] if kat and kat["dienst_adressen"] else ([r["dienst"]] if r["dienst"] else []),
        "parameter": kat["parameter"] if kat else {},
    }


def _rows(nur_aktiv):
    return [r for r in zeilen() if genutzt(r, nur_aktiv)]


def _gruppen(rows):
    """Exporte sind immer nach Thema gruppiert."""
    return gruppen("Thema", rows)


def _kopf(rows, gr):
    return f"Stand {STAND} · {len(rows)} Quellen in {len(gr)} Kategorien. Erzeugt aus `datenquellen_alle.py`."


def export_json(gruppierung="Thema", nur_aktiv=False):
    rows = _rows(nur_aktiv)
    return json.dumps({"titel": TITEL, "stand": STAND, "anzahl": len(rows), "quellen": [eintrag(r) for r in rows]},
                      ensure_ascii=False, indent=2)


def export_csv(gruppierung=None, nur_aktiv=False):
    """Eine Zeile je Quelle; Semikolon und UTF-8 mit BOM für Excel."""
    spalten = [("ID", "id"), ("Name", "name"), ("Thema", "thema"), ("Kurzbeschreibung", "kurzbeschreibung"),
               ("Wofür / liefert", "stichworte"), ("Beschreibung", "beschreibung"), ("Art", "art"),
               ("Anbindung", "anbindung"), ("Anbieter", "anbieter"), ("Lizenz", "lizenz"), ("Webseite", "webseite"),
               ("Dienst-Adressen", "dienst_adressen"), ("Parameter", "parameter")]
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    w.writerow([t for t, _ in spalten])
    for r in _rows(nur_aktiv):
        e = eintrag(r)
        zeile = []
        for _, k in spalten:
            v = e[k]
            if k == "stichworte":
                v = ", ".join(v)
            elif k == "dienst_adressen":
                v = " | ".join(v)
            elif k == "parameter":
                v = " | ".join(f"{p}: {t}" for p, t in v.items())
            zeile.append(v or "")
        w.writerow(zeile)
    return ("﻿" + buf.getvalue()).encode("utf-8")


# ---------------------------------------------------------------------------------------------------- Markdown
def _md(text):
    return str(text).replace("|", "/").replace("\n", " ")


def _mit_stichworten(liste):
    """Spalte 'Wofür / liefert' nur, wenn eine Quelle der Gruppe Stichworte hat (aus Aarons Katalog)."""
    return any(eintrag(r)["stichworte"] for r in liste)


def _md_tabelle(liste):
    sw = _mit_stichworten(liste)
    z = ["| Quelle | Beschreibung | " + ("Wofür / liefert | " if sw else "") + "Anbieter |",
         "|---|---|---|" + ("---|" if sw else "")]
    for r in liste:
        e = eintrag(r)
        anb = doku.anbieter_kurz(e["anbieter"])
        z.append(f"| [{_md(e['name'])}](#q-{e['id']}) | {_md(e['kurzbeschreibung'])} | " +
                 (f"{_md(', '.join(e['stichworte']))} | " if sw else "") +
                 (f"[{_md(anb)}]({e['webseite']}) |" if e["webseite"] else f"{_md(anb)} |"))
    return z + [""]


def _md_quelle(r):
    e = eintrag(r)
    z = [f'<a id="q-{e["id"]}"></a>', "", f"#### {e['name']}", "", e["beschreibung"] or e["kurzbeschreibung"], ""]
    if e["stichworte"]:
        z.append(f"- **Wofür / liefert:** {', '.join(e['stichworte'])}")
    if e["art"]:
        z.append(f"- **Art:** {e['art']} · **Anbindung:** {e['anbindung']}")
    z.append(f"- **Anbieter:** {e['anbieter']}" + (f" · **Lizenz:** {e['lizenz']}" if e["lizenz"] else ""))
    if e["webseite"]:
        z.append(f"- **Webseite / Doku:** [{urlparse(e['webseite']).netloc.removeprefix('www.')}]({e['webseite']})")
    if e["dienst_adressen"]:
        z.append("- **Dienst-Adresse" + ("n" if len(e["dienst_adressen"]) > 1 else "") + ":** " +
                 " · ".join(f"`{a}`" for a in e["dienst_adressen"]))
    z.append("")
    if e["parameter"]:
        z += ["| Parameter | Bedeutung |", "|---|---|", *[f"| `{k}` | {_md(t)} |" for k, t in e["parameter"].items()], ""]
    return z


def export_markdown(gruppierung="Thema", nur_aktiv=False):
    """Aufbau wie die Doku: 1. alle Kategorien als Tabellen, 2. je Kategorie die Quellen mit kurzen Infos."""
    rows = _rows(nur_aktiv)
    gr = _gruppen(rows)
    z = [f"# {TITEL}", "", _kopf(rows, gr), "",
         "Inhalt: [Alle Kategorien im Überblick](#ueberblick) · [Quellen je Kategorie](#details)", "",
         '<a id="ueberblick"></a>', "", "## Alle Kategorien im Überblick", ""]
    for titel, symbol, info, liste in gr:
        z += [f"### [{symbol} {titel}](#{doku.slug(titel)}) ({len(liste)})", ""] + ([info, ""] if info else [])
        z += _md_tabelle(liste)
    z += ['<a id="details"></a>', "", "## Quellen je Kategorie", ""]
    for titel, symbol, info, liste in gr:
        z += [f'<a id="{doku.slug(titel)}"></a>', "", f"### {symbol} {titel}", ""] + ([info, ""] if info else [])
        for r in liste:
            z += _md_quelle(r)
    return "\n".join(z) + "\n"


# ---------------------------------------------------------------------------------------------------- HTML / PDF
def _h(text):
    return html.escape(str(text))


HTML_CSS_ZUSATZ = """
table.quellen th:nth-child(1){width:24%} table.quellen th:nth-child(2){width:36%} table.quellen th:nth-child(3){width:22%}
table.quellen th:nth-child(4){width:18%}
table.quellen.ohne-sw th:nth-child(2){width:52%} table.quellen.ohne-sw th:nth-child(3){width:24%}
"""


def _html_tabelle(liste):
    sw = _mit_stichworten(liste)
    t = [f"<table class='quellen{'' if sw else ' ohne-sw'}'><tr><th>Quelle</th><th>Beschreibung</th>" +
         ("<th>Wofür / liefert</th>" if sw else "") + "<th>Anbieter</th></tr>"]
    for r in liste:
        e = eintrag(r)
        anb = _h(doku.anbieter_kurz(e["anbieter"]))
        if e["webseite"]:
            anb = f"<a href='{_h(e['webseite'])}'>{anb}</a>"
        tags = "".join(f"<span class=tag>{_h(w)}</span>" for w in e["stichworte"])
        t.append(f"<tr><td><a href='#q-{_h(e['id'])}'><b>{_h(e['name'])}</b></a></td><td>{_h(e['kurzbeschreibung'])}</td>"
                 + (f"<td>{tags}</td>" if sw else "") + f"<td>{anb}</td></tr>")
    return "\n".join(t) + "</table>"


def _html_quelle(r):
    e = eintrag(r)
    zeilen = []
    if e["stichworte"]:
        zeilen.append(f"<b>Wofür / liefert:</b> {''.join(f'<span class=tag>{_h(w)}</span>' for w in e['stichworte'])}")
    if e["art"]:
        zeilen.append(f"<b>Art:</b> {_h(e['art'])} · <b>Anbindung:</b> {_h(e['anbindung'])}")
    zeilen.append(f"<b>Anbieter:</b> {_h(e['anbieter'])}" + (f" · <b>Lizenz:</b> {_h(e['lizenz'])}" if e["lizenz"] else ""))
    if e["webseite"]:
        zeilen.append(f"<b>Webseite / Doku:</b> <a href='{_h(e['webseite'])}'>"
                      f"{_h(urlparse(e['webseite']).netloc.removeprefix('www.'))}</a>")
    if e["dienst_adressen"]:
        zeilen.append("<b>Dienst-Adresse" + ("n" if len(e["dienst_adressen"]) > 1 else "") + ":</b> " +
                      " · ".join(f"<code>{_h(a)}</code>" for a in e["dienst_adressen"]))
    t = [f"<section class='quelle' id='q-{_h(e['id'])}'><h4>{_h(e['name'])}</h4>",
         f"<p>{_h(e['beschreibung'] or e['kurzbeschreibung'])}</p><p>" + "<br>".join(zeilen) + "</p>"]
    if e["parameter"]:
        t.append("<table class='kv'><tr><th>Parameter</th><th>Bedeutung</th></tr>" + "".join(
            f"<tr><td><code>{_h(k)}</code></td><td>{_h(v)}</td></tr>" for k, v in e["parameter"].items()) + "</table>")
    t.append("</section>")
    return "\n".join(t)


def export_html(gruppierung="Thema", nur_aktiv=False):
    """Eigenständige HTML-Seite (auch Vorlage für das PDF). Aufbau und Aussehen wie die Doku."""
    rows = _rows(nur_aktiv)
    gr = _gruppen(rows)
    t = [f"<!doctype html><html lang='de'><head><meta charset='utf-8'>"
         f"<meta name='viewport' content='width=device-width,initial-scale=1'><title>{_h(TITEL)}</title>"
         f"<style>{doku.HTML_CSS}{HTML_CSS_ZUSATZ}</style></head><body><main>",
         f"<h1>{_h(TITEL)}</h1><p class='muted'>Stand {STAND} · {len(rows)} Quellen in {len(gr)} Kategorien. "
         "Erzeugt aus <code>datenquellen_alle.py</code>.</p>",
         "<p class='muted'>Inhalt: <a href='#ueberblick'>Alle Kategorien im Überblick</a> · "
         "<a href='#details'>Quellen je Kategorie</a></p>",
         "<h2 id='ueberblick'>Alle Kategorien im Überblick</h2>"]
    for titel, symbol, info, liste in gr:
        t.append(f"<h3><a href='#{doku.slug(titel)}'>{symbol} {_h(titel)}</a> <span class='muted'>({len(liste)})</span></h3>" +
                 (f"<p class='muted'>{_h(info)}</p>" if info else "") + _html_tabelle(liste))
    t.append("<h2 class='teil' id='details'>Quellen je Kategorie</h2>")
    for titel, symbol, info, liste in gr:
        t.append(f"<h3 class='gruppe' id='{doku.slug(titel)}'>{symbol} {_h(titel)}</h3>" +
                 (f"<p class='muted'>{_h(info)}</p>" if info else ""))
        t += [_html_quelle(r) for r in liste]
    t.append("</main></body></html>")
    return "\n".join(t)


def export_pdf(gruppierung="Thema", nur_aktiv=False):
    """PDF wie bei der Doku: die HTML-Seite druckt Edge/Chrome ohne Fenster als A4-PDF."""
    browser = doku.browser_pfad()
    if not browser:
        raise RuntimeError("Für PDF wird Microsoft Edge oder Google Chrome gebraucht (oder PDF_BROWSER setzen).")
    tmp = tempfile.mkdtemp(prefix="datenquellen_alle_pdf_")
    try:
        html_pfad, pdf_pfad = os.path.join(tmp, "vergleich.html"), os.path.join(tmp, "vergleich.pdf")
        with open(html_pfad, "w", encoding="utf-8") as f:
            f.write(export_html(gruppierung, nur_aktiv))
        # eigenes Profil: läuft auch, wenn der Browser gerade offen ist
        subprocess.run([browser, "--headless=new", "--disable-gpu", "--no-first-run", "--no-pdf-header-footer",
                        f"--user-data-dir={os.path.join(tmp, 'profil')}", f"--print-to-pdf={pdf_pfad}",
                        pathlib.Path(html_pfad).as_uri()],
                       capture_output=True, timeout=180, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        for _ in range(50):  # manche Versionen schreiben die Datei kurz nach Prozessende fertig
            if os.path.exists(pdf_pfad) and os.path.getsize(pdf_pfad) > 0:
                break
            time.sleep(0.1)
        else:
            raise RuntimeError(f"{os.path.basename(browser)} hat kein PDF erzeugt.")
        time.sleep(0.2)
        with open(pdf_pfad, "rb") as f:
            return f.read()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


EXPORTE = {  # Format: (Dateiendung, MIME-Typ, Funktion(gruppierung, nur_aktiv) -> str | bytes)
    "md": ("md", "text/markdown", export_markdown),
    "html": ("html", "text/html", export_html),
    "pdf": ("pdf", "application/pdf", export_pdf),
    "csv": ("csv", "text/csv", export_csv),
    "json": ("json", "application/json", export_json),
}


def dateiname(fmt, nur_aktiv=False):
    return f"datenquellen_alle_prototypen{'_aktiv' if nur_aktiv else ''}_{datetime.date.today().isoformat()}.{fmt}"


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    ordner = sys.argv[1] if len(sys.argv) > 1 else os.path.join(dq.HERE, "output", "doku")
    gruppierung = sys.argv[2] if len(sys.argv) > 2 else "Thema"
    os.makedirs(ordner, exist_ok=True)
    for fmt, (_, _, fn) in EXPORTE.items():
        inhalt = fn(gruppierung)
        pfad = os.path.join(ordner, dateiname(fmt))
        with open(pfad, "wb") as f:
            f.write(inhalt if isinstance(inhalt, bytes) else inhalt.encode("utf-8"))
        print(f"{pfad}  ({os.path.getsize(pfad) // 1024} KB)")
