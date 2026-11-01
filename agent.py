"""
Geo-Agent: Ein LLM entscheidet selbst, welche Geo-Tools es aufruft
(OpenStreetMap-Daten holen, QGIS-Algorithmen suchen/ausführen, Karte erzeugen).

Modell wählen (in .env): MODEL=gemma | flash-lite | nemotron | flint   (siehe PRESETS unten)
Start:  python agent.py   (Terminal)   bzw.   streamlit run app.py   (Browser-Oberfläche)
Ende:   "exit" eingeben oder Strg+C
"""
import json
import os
import sys
import time
import urllib.request

import openai
from dotenv import load_dotenv
from google import genai
from google.genai import errors, types

import annahmen as annahmen_mod
import climate_tools
import datenquellen
import geo_tools
import impact_tools
import ladeinfra_tools

HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(HERE, ".env"))

# Umschalter: in .env  MODEL=<kurzname>  setzen. Alle kostenlos.
PRESETS = {
    "gemma":      ("gemini", "gemma-4-31b-it"),                       # Google Gemma 4 31B
    "flash-lite": ("gemini", "gemini-3.5-flash-lite"),                # Google Gemini 3.5 Flash Lite
    "nemotron":   ("openrouter", "nvidia/nemotron-3.5-super-vl:free"),  # NVIDIA Nemotron 3.5 Super
    "flint":      ("openrouter", "recursive/flint-v1.0:free"),        # Recursive AI Flint
}
DEFAULT_PRESET = "gemma"
GEMINI_MODEL = PRESETS["gemma"][1]
OPENROUTER_MODEL = PRESETS["nemotron"][1]
MAX_STEPS = 30  # Sicherheitsgrenze: max. Tool-Runden pro Frage
GEO_EXT = (".geojson", ".gpkg", ".shp", ".csv", ".tif", ".tiff", ".json", ".kml", ".gml")

SYSTEM_BASIS = """Du bist ein Geo-Agent für Mitarbeitende in Kommunen, die keine GIS-Expert:innen sind.
Du löst räumliche Fragen, indem du offene Daten holst und bestehende GIS-Werkzeuge (QGIS-Processing, GDAL) ausführst.

Arbeitsweise:
- Bestimme den Ort zuerst mit geocode (Kreuzungen als "Straße A / Straße B, Stadt").
- Hole Daten mit datenquelle_abfragen (freie Datenquellen, Liste unten) und fetch_osm (OpenStreetMap-Objekte; Gebiet als bbox [süd, west, nord, ost] in WGS84).
- Suche passende QGIS-Algorithmen mit list_qgis_algorithms, prüfe Parameter mit qgis_algorithm_help, bevor du ein Werkzeug zum ersten Mal ausführst.
- Für Abstände/Puffer in Metern vorher nach EPSG:25832 (UTM 32N) umprojizieren; für die Karte am Ende nach EPSG:4326.
- Zwischenergebnisse immer als Datei speichern (z.B. "puffer.gpkg"), niemals "memory:" oder TEMPORARY_OUTPUT. Relative Dateinamen landen im Ergebnisordner der aktuellen Frage; Dateien aus früheren Fragen werden über ihren Namen gefunden.
- Zeige Ergebnisse mit make_map (nur GeoJSON in EPSG:4326). Die Karte hat Luftbild und Liegenschaftskarte Hessen als Hintergrund zum Umschalten."""

SYSTEM_DATEN = f"""Freie Datenquellen (alle ohne API-Key) - Aufruf: datenquelle_abfragen mit quelle, lat, lon, radius_m und ggf. parameter:
{datenquellen.katalog_text()}

Hinweise zu den Datenquellen:
- Nutze für eine Frage mehrere passende Quellen und vergleiche sie, typisch:
  Starkregen/Überflutung: kostra_starkregen (amtliche Regenmengen), hlnug_starkregen (Hinweiskarte, Fließpfade), hlnug_hochwasser, copernicus_versiegelung, hlnug_boden, gelaendehoehe; aktuell: regenradar, unwetterwarnungen.
  Hitze/Stadtklima: landsat_oberflaechentemperatur, hlnug_hitze, stadtklima_waermeinsel, copernicus_baumbedeckung, copernicus_versiegelung, sentinel2_ndvi, dwd_klimaraster (heisse_tage), klima_projektion.
  Ladesäulen/Energie: ladesaeulen_register, zensus2022, marktstammdaten, oepnv_haltestellen, erreichbarkeit, fetch_osm ("amenity"="parking", "power"="substation").
  Baustelle/Verkehr/Lärm: hlnug_laerm, unfallatlas, autobahn, oepnv_haltestellen, oepnv_abfahrten, zensus2022, fetch_osm (Schulen "amenity"="school", Kitas "amenity"="kindergarten").
  Natur/Bauvorhaben: hlnug_schutzgebiete, schutzgebiete_bund, hlnug_biotope, gbif_arten, hlnug_wasserschutz, hlnug_geologie, hlnug_radon, wikidata (Denkmäler).
  Luft/Gesundheit: luft_messstationen, luft_modell, buergersensoren_luft, pollenflug, uv_index.
- Weitere Daten finden: opendata_darmstadt, govdata, geoportal_hessen; laden mit datei_laden, wfs_abfrage, arcgis_abfrage, wms_abfrage.
- Jedes Ergebnis enthält "quelle" (Anbieter, Lizenz, Stand), eine "zusammenfassung" und ggf. "files" (GeoJSON für make_map oder als Eingabe für QGIS).
- Liefert eine Quelle einen Fehler, sag das kurz und nimm eine andere. Erfinde keine Werte. Details zu Parametern: datenquellen_katalog."""

SYSTEM_NUR_DATEN = """Modus "Nur Datenquellen": Es gibt KEINE fertigen Analyse-Werkzeuge (kein starkregen, hitze, ladesaeulen, traffic_impact, construction_noise).
- Beantworte Fragen nur mit Daten aus datenquelle_abfragen und fetch_osm und mit bestehenden QGIS-Algorithmen (z.B. Puffer, Verschneiden, Zonenstatistik, Join by location, Punkte in Polygon zählen).
- Rechne keine eigenen Modelle im Kopf. Beschreibe, was die Daten zeigen (Werte, Anteile, Vergleiche) und ordne vorsichtig ein.
  Bei Was-wäre-wenn-Fragen ("wenn wir pflastern", "wenn wir Bäume fällen"): Ist-Zustand aus den Daten zeigen, die Richtung der Änderung mit Begründung aus den Daten nennen, keine erfundenen Zahlen.
- Beende jede Antwort mit einer Tabelle "Annahmen" (| Annahme | Wert | Einheit | Begründung |) für deine eigenen Festlegungen (Radius, Zeitraum, Schwellen, Auswahl der Quellen)."""

SYSTEM_SCHLUSS = """Am Ende JEDER Antwort, in der du Datenquellen genutzt hast, eine Tabelle "Datenquellen" mit | Quelle | Anbieter | Stand | Lizenz | (aus dem Feld "quelle" der Ergebnisse; OSM: OpenStreetMap, ODbL).
- Dateien aus Werkzeug-Ergebnissen sind kurze Namen (z.B. "versiegelung_copernicus.geojson"): genau so an make_map übergeben.
- Antworte in der Sprache der Nutzerin / des Nutzers, kurz und verständlich, und nenne die Zahlen und Annahmen (z.B. Pufferradius), auf denen dein Ergebnis beruht."""

SYSTEM_SKILLS = f"""Eigene Analyse-Werkzeuge (Skills) sind eingeschaltet. Ergänze sie mit passenden Datenquellen
(z.B. kostra_starkregen für niederschlag_mm, copernicus_baumbedeckung als Prüfung der OSM-Bäume, hlnug_laerm für den heutigen Lärm).

Fragen zu Baustellen / Sperrungen ("Was bedeutet eine Baustelle an X für Lärm und Verkehr?"):
1. geocode mit dem Ort (Kreuzungen als "Straße A / Straße B, Stadt").
2. traffic_impact und/oder construction_noise mit lat/lon, je nachdem was gefragt ist (bei "Auswirkungen" allgemein beides). Bei construction_noise die Tätigkeit passend wählen (normal / laut / sehr_laut).
3. make_map mit den zurückgegebenen Dateien in dieser Reihenfolge: laermringe, verkehr, sperrung, einrichtungen.
4. Antwort: gesperrte Straßen, Anteil betroffener Fahrten und Umweg, Straßen mit mehr Verkehr (+ dB), Lärmradien, Anzahl Gebäude ab 65/55 dB(A), sensible Einrichtungen mit überschrittenem Richtwert.
   Sag klar, dass es eine grobe Abschätzung ist (keine echten Verkehrsmengen, keine Gebäudeabschirmung).

Fragen zu Starkregen und Hitze ("Was passiert bei Starkregen, wenn wir hier pflastern?", "Wird es wärmer, wenn wir Bäume fällen / versiegeln?"):
1. geocode mit dem Ort.
2. starkregen (Wasser, Überflutung) bzw. hitze (Temperatur, Bäume, Schatten); bei "Klima-Auswirkungen" allgemein beides.
   Größe der Fläche als radius_m: aus einer Fläche in m² ist radius_m = Wurzel(Fläche / 3,14). Ohne Angabe 50 m nehmen und das sagen.
   Maßnahme passend wählen: pflastern -> versiegeln, Straße/Asphalt -> asphaltieren, Bäume fällen -> baeume_faellen, begrünen -> entsiegeln, Bäume pflanzen -> baeume_pflanzen.
3. make_map mit den zurückgegebenen Dateien in dieser Reihenfolge: starkregen: wasser, fliesswege, mehr_wasser, massnahme, gebaeude; hitze: temperatur, massnahme, einrichtungen.
4. Antwort Starkregen: zusätzlicher Abfluss in m³, wohin das Wasser fließt (Senken mit Ort, Tiefe vorher/nachher), betroffene Gebäude/Einrichtungen.
   Antwort Hitze: Bäume/Kronenfläche und Versiegelung vorher/nachher, Oberflächentemperatur, Lufttemperatur-Änderung mit Spanne und Reichweite, betroffene Einrichtungen.
   Sag klar, dass es eine grobe Abschätzung ist, und nenne die "warnungen" und Datenlücken (Höhenmodell grob, Bäume in OSM unvollständig).

Fragen zu E-Ladesäulen ("Wo könnten Ladesäulen sinnvoll sein?", "Wo fehlen Ladesäulen?", "Wo lohnt sich ein Schnelllader?"):
1. geocode mit dem Ort (Stadt, Stadtteil oder Platz).
2. ladesaeulen mit lat/lon. radius_m: Stadtteil 1000-1500, ganze Stadt 2500-3000. e_auto_anteil: Standard 0,15 (Szenario ca. 2030);
   wenn nach "heute" gefragt ist ca. 0,05. Für einen Vergleich das Werkzeug zweimal mit verschiedenen Anteilen aufrufen.
   Bevorzuge dieses Werkzeug statt eigener QGIS-Puffer, weil es Bedarf (Zensus), Bestand (BNetzA), Verkehr und Stromnetz zusammenführt.
3. make_map mit den Dateien in dieser Reihenfolge: bedarf, verkehr, netz, bestand, standorte.
4. Antwort: Szenario (E-Autos, öffentlicher Bedarf, vorhandene Ladepunkte, Lücke in Ladepunkten), die besten Standorte als Liste mit Typ
   (AC/DC), Zahl der Ladepunkte und Begründung, Hinweise zum Stromnetz (Abstand Trafostation, Zusatzlast).
   Sag klar: grobe Abschätzung, Netzkapazitäten sind nicht öffentlich (nur Lage der Stationen aus OSM), Verkehr ist simuliert,
   Flächen sind nicht auf Verfügbarkeit geprüft. Für echte Planung: Netzbetreiber (e-netz Südhessen) und Verkehrszählungen der Stadt.

Annahmen (gilt für traffic_impact, construction_noise, starkregen, hitze, ladesaeulen):
- Jedes dieser Werkzeuge rechnet mit Annahmen (Faktoren, Gewichte, Schwellen). ALLE sind über den Parameter "annahmen" änderbar,
  z.B. {{"kanal_mm": 25}} oder {{"gewichte_ac": {{"netz": 0.4}}}} (bei Einträgen wie gewichte_ac reicht der geänderte Eintrag).
- Nennt die Nutzerin andere Werte ("rechne mit 0,5 Pkw je Einwohner", "Kanal schafft 20 mm"), übergib sie in "annahmen".
  Unbekannte Namen lehnt das Werkzeug mit der Liste der erlaubten Namen ab: dann den richtigen Namen nehmen und neu aufrufen.
- Das Ergebnis enthält immer die Liste "annahmen" (annahme, wert, einheit, geaendert, wichtig).
  Beende JEDE Antwort mit einer Markdown-Tabelle "Annahmen" mit den Spalten | Annahme | Wert | Einheit | geändert? |.
  Darin: alle Zeilen mit "wichtig": true und alle mit "geaendert": true (geänderte mit altem Standardwert, z.B. "25 (statt 10)").
  Darunter ein Satz: alle weiteren Annahmen stehen vollständig unter der Antwort und lassen sich ändern.
  Nutzt du keines dieser Werkzeuge, gilt stattdessen: Tabelle "Annahmen" mit deinen eigenen Festlegungen (| Annahme | Wert | Einheit | Begründung |)."""

SKILL_NAMES = ("traffic_impact", "construction_noise", "starkregen", "ladesaeulen", "hitze")


def system_prompt(skills=True):
    """Systemprompt je Modus: mit eigenen Analyse-Skills oder nur Datenquellen + QGIS."""
    teile = [SYSTEM_BASIS, SYSTEM_DATEN, SYSTEM_SKILLS if skills else SYSTEM_NUR_DATEN, SYSTEM_SCHLUSS]
    return "\n\n".join(teile)


SYSTEM = system_prompt(True)  # für Rückwärtskompatibilität

TOOLS = [
    {
        "name": "datenquelle_abfragen",
        "description": "Fragt eine freie Datenquelle ab (über 50: Wetter, Klima, Starkregen, Hitze, Lärm, Schutzgebiete, Boden, "
                       "Zensus, Unfälle, ÖPNV, Energie, Satellitenbilder, Open-Data-Kataloge ...; Liste im Systemprompt). "
                       "Liefert Zusammenfassung, Metadaten (Anbieter, Lizenz, Stand) und ggf. GeoJSON-Dateien für make_map oder QGIS.",
        "schema": {
            "type": "object",
            "properties": {
                "quelle": {"type": "string", "enum": list(datenquellen.QUELLEN), "description": "ID der Datenquelle"},
                "lat": {"type": "number"}, "lon": {"type": "number"},
                "radius_m": {"type": "number", "description": "Umkreis in Metern (ohne Angabe: Standard der Quelle)"},
                "parameter": {"type": "object", "description": 'Quellen-spezifische Parameter laut Liste, z.B. {"tage": 7}, '
                                                               '{"jahre": [2023, 2024]} oder {"suche": "Verkehr"}'},
            },
            "required": ["quelle"],
        },
    },
    {
        "name": "datenquellen_katalog",
        "description": "Details zu den freien Datenquellen (Parameter, Lizenz, Anbieter, Standard-Umkreis), optional gefiltert nach Kategorie oder Stichwort.",
        "schema": {
            "type": "object",
            "properties": {"kategorie": {"type": "string", "description": "z.B. 'Wetter', 'Mobilität', 'Satellit'"},
                           "suche": {"type": "string", "description": "Stichwort, z.B. 'Lärm' oder 'Bäume'"}},
        },
    },
    {
        "name": "fetch_osm",
        "description": "Lädt OpenStreetMap-Objekte (Punkte; Flächen als Mittelpunkt) in einem Gebiet über die Overpass API und speichert sie als GeoJSON (EPSG:4326). Gibt Pfad und Anzahl zurück.",
        "schema": {
            "type": "object",
            "properties": {
                "tag_filter": {"type": "string", "description": 'Overpass-Tagfilter, z.B. "amenity"="parking" oder "amenity"="charging_station"'},
                "bbox": {"type": "array", "items": {"type": "number"},
                         "description": "[süd, west, nord, ost] in Grad, z.B. [49.86, 8.63, 49.885, 8.68]"},
                "filename": {"type": "string", "description": "Dateiname für das Ergebnis, z.B. parkplaetze.geojson"},
            },
            "required": ["tag_filter", "bbox", "filename"],
        },
    },
    {
        "name": "list_qgis_algorithms",
        "description": "Durchsucht die installierten QGIS-Processing-Algorithmen (~700, inkl. GDAL und GRASS) nach einem Stichwort in ID oder Name (englisch, z.B. 'buffer', 'reproject', 'join', 'distance'). Gibt id + name zurück.",
        "schema": {
            "type": "object",
            "properties": {"search": {"type": "string", "description": "Stichwort, englisch"}},
            "required": ["search"],
        },
    },
    {
        "name": "qgis_algorithm_help",
        "description": "Beschreibung, Parameter und Ausgaben eines QGIS-Algorithmus, z.B. native:buffer.",
        "schema": {
            "type": "object",
            "properties": {"algorithm_id": {"type": "string"}},
            "required": ["algorithm_id"],
        },
    },
    {
        "name": "run_qgis_algorithm",
        "description": "Führt einen QGIS-Processing-Algorithmus aus. Gibt die Ergebnisse (z.B. OUTPUT-Pfad) zurück.",
        "schema": {
            "type": "object",
            "properties": {
                "algorithm_id": {"type": "string"},
                "parameters_json": {"type": "string", "description": 'Parameter als JSON-Text, wie in qgis_algorithm_help. Enums als Zahl oder Liste. Beispiel: {"INPUT": "a.geojson", "DISTANCE": 400, "OUTPUT": "b.gpkg"}'},
            },
            "required": ["algorithm_id", "parameters_json"],
        },
    },
    {
        "name": "make_map",
        "description": "Erzeugt eine interaktive HTML-Karte (Leaflet + OSM) aus GeoJSON-Dateien in EPSG:4326. Erste Datei wird zuunterst gezeichnet.",
        "schema": {
            "type": "object",
            "properties": {
                "geojson_files": {"type": "array", "items": {"type": "string"}},
                "filename": {"type": "string", "description": "z.B. karte.html"},
            },
            "required": ["geojson_files"],
        },
    },
    {
        "name": "geocode",
        "description": "Findet die Koordinaten einer Adresse, eines Ortes oder einer Kreuzung in Deutschland. Kreuzungen im Format 'Straße A / Straße B, Stadt'.",
        "schema": {
            "type": "object",
            "properties": {"place": {"type": "string", "description": "z.B. 'Rheinstraße / Neckarstraße, Darmstadt' oder 'Karolinenplatz, Darmstadt'"}},
            "required": ["place"],
        },
    },
    {
        "name": "traffic_impact",
        "description": "Abschätzung, wohin sich der Durchgangsverkehr verlagert, wenn die Straßen an einem Punkt gesperrt werden (Baustelle). Liefert gesperrte Straßen, Anteil betroffener Fahrten, Umwege, Straßen mit mehr/weniger Verkehr samt Verkehrslärm-Änderung in dB, sowie GeoJSON-Dateien für die Karte.",
        "schema": {
            "type": "object",
            "properties": {
                "lat": {"type": "number"}, "lon": {"type": "number"},
                "radius_m": {"type": "number", "description": "Untersuchungsgebiet in Metern, Standard 1500"},
                "closure_m": {"type": "number", "description": "Sperrung: alle Straßenabschnitte bis zu diesem Abstand vom Punkt, Standard 30"},
            },
            "required": ["lat", "lon"],
        },
    },
    {
        "name": "construction_noise",
        "description": "Abschätzung des Baulärms: Lärmringe (75/70/65/60/55 dB(A)), Anzahl betroffener Gebäude, sensible Einrichtungen (Schulen, Kitas, Kliniken, Pflegeheime) mit Pegel und Richtwert nach AVV Baulärm, sowie GeoJSON-Dateien für die Karte.",
        "schema": {
            "type": "object",
            "properties": {
                "lat": {"type": "number"}, "lon": {"type": "number"},
                "activity": {"type": "string", "enum": ["normal", "laut", "sehr_laut"],
                             "description": "normal = Bagger/Lkw (105 dB), laut = Abbruch/Stemmen (112 dB), sehr_laut = Rammen (120 dB)"},
            },
            "required": ["lat", "lon"],
        },
    },
    {
        "name": "starkregen",
        "description": "Abschätzung: Was passiert bei Starkregen, wenn eine Fläche versiegelt oder entsiegelt wird? Liefert zusätzlichen Oberflächenabfluss (m³), Senken, in denen sich Wasser sammelt (Tiefe vorher/nachher, Ort), betroffene Gebäude und sensible Einrichtungen, Fließwege, sowie GeoJSON-Dateien für die Karte.",
        "schema": {
            "type": "object",
            "properties": {
                "lat": {"type": "number"}, "lon": {"type": "number"},
                "radius_m": {"type": "number", "description": "Größe der Fläche als Kreisradius in Metern, Standard 50"},
                "massnahme": {"type": "string", "enum": ["versiegeln", "asphaltieren", "entsiegeln"],
                              "description": "versiegeln = pflastern, asphaltieren = Straße/Asphalt, entsiegeln = zu Grünfläche"},
                "niederschlag_mm": {"type": "number", "description": "Regen in 1 Stunde, Standard 50 (seltener Starkregen, ca. 100-jährlich)"},
            },
            "required": ["lat", "lon"],
        },
    },
    {
        "name": "ladesaeulen",
        "description": "Standortanalyse für öffentliche E-Ladesäulen: Ladebedarf aus Zensus 2022 (Einwohner, Mehrfamilienhäuser, Eigentümerquote) und Zielen (Supermärkte, Uni, Kliniken ...), Bestand aus dem Ladesäulenregister der Bundesnetzagentur, Verkehrs-Simulation auf dem Straßennetz, Abstand zu Trafostationen (Stromnetz). Liefert Szenario-Zahlen, die besten Standorte mit Typ (AC-Normalladen / DC-Schnellladen), Zahl der Ladepunkte und Begründung sowie GeoJSON-Dateien für die Karte.",
        "schema": {
            "type": "object",
            "properties": {
                "lat": {"type": "number"}, "lon": {"type": "number"},
                "radius_m": {"type": "number", "description": "Untersuchungsgebiet in Metern, Standard 1500 (Stadtteil); ganze Stadt 2500-3000"},
                "e_auto_anteil": {"type": "number", "description": "Anteil E-Autos am Pkw-Bestand, 0-1. Standard 0.15 (Szenario ca. 2030), heute ca. 0.05"},
                "anzahl": {"type": "integer", "description": "Wie viele Standorte vorschlagen, Standard 10"},
            },
            "required": ["lat", "lon"],
        },
    },
    {
        "name": "hitze",
        "description": "Abschätzung: Wird es wärmer, wenn Bäume gefällt oder Flächen versiegelt werden (bzw. kühler beim Begrünen)? Liefert entfallende Bäume, Kronenfläche und Versiegelung vorher/nachher, Oberflächentemperatur, Änderung der Lufttemperatur an einem heißen Sommernachmittag mit Spanne und Reichweite, betroffene sensible Einrichtungen, sowie GeoJSON-Dateien für die Karte.",
        "schema": {
            "type": "object",
            "properties": {
                "lat": {"type": "number"}, "lon": {"type": "number"},
                "radius_m": {"type": "number", "description": "Größe der Fläche als Kreisradius in Metern, Standard 50"},
                "massnahme": {"type": "string",
                              "enum": ["baeume_faellen", "versiegeln", "asphaltieren", "entsiegeln", "baeume_pflanzen"]},
            },
            "required": ["lat", "lon"],
        },
    },
]


# Parameter "annahmen" für die eigenen Werkzeuge, automatisch aus den Standardwerten erzeugt
ANNAHMEN_DEFAULTS = {
    "traffic_impact": impact_tools.VERKEHR_DEFAULTS, "construction_noise": impact_tools.LAERM_DEFAULTS,
    "starkregen": climate_tools.STARKREGEN_DEFAULTS, "hitze": climate_tools.HITZE_DEFAULTS,
    "ladesaeulen": ladeinfra_tools.DEFAULTS,
}
for _t in TOOLS:
    if _t["name"] in ANNAHMEN_DEFAULTS:
        _t["schema"]["properties"]["annahmen"] = annahmen_mod.schema(ANNAHMEN_DEFAULTS[_t["name"]])


def tools_for(skills=True):
    """Werkzeuge je Modus: ohne Skills nur Datenquellen, OSM, QGIS, Geocoding und Karte."""
    return [t for t in TOOLS if skills or t["name"] not in SKILL_NAMES]


def _resolve_params(params):
    """Relative Dateinamen in QGIS-Parametern: Ausgaben (OUTPUT...) in den Ergebnisordner der Frage,
    Eingaben dort oder in früheren Ergebnisordnern suchen."""
    fixed = {}
    for key, value in params.items():
        if isinstance(value, str) and value.lower().endswith(GEO_EXT) and not os.path.isabs(value):
            value = geo_tools.out_path(value) if key.upper().startswith("OUTPUT") else geo_tools.find_path(value)
        fixed[key] = value
    return fixed


def execute_tool(name, args, skills=True):
    if not skills and name in SKILL_NAMES:
        raise ValueError(f"'{name}' ist im Modus 'Nur Datenquellen' ausgeschaltet. Nutze datenquelle_abfragen und QGIS-Algorithmen.")
    result = _execute_tool(name, args)
    # Kurze Dateinamen statt langer Pfade: das Modell schreibt sie fehlerfrei ab, make_map findet sie im Ergebnisordner
    if isinstance(result, dict) and isinstance(result.get("files"), dict):
        result["files"] = {k: os.path.basename(v) for k, v in result["files"].items()}
    return result


def _execute_tool(name, args):
    if name == "datenquelle_abfragen":
        return datenquellen.abfragen(args["quelle"], args.get("lat"), args.get("lon"), args.get("radius_m"),
                                     args.get("parameter"))
    if name == "datenquellen_katalog":
        return {"quellen": datenquellen.katalog(args.get("kategorie"), args.get("suche"))}
    if name == "fetch_osm":
        return geo_tools.fetch_osm(args["tag_filter"], tuple(args["bbox"]), geo_tools.out_path(args["filename"]))
    if name == "list_qgis_algorithms":
        algs = geo_tools.list_algorithms(args["search"])
        return {"count": len(algs), "algorithms": algs[:80]}
    if name == "qgis_algorithm_help":
        h = geo_tools.algorithm_help(args["algorithm_id"])
        return {k: h[k] for k in ("algorithm_details", "parameters", "outputs") if k in h}
    if name == "run_qgis_algorithm":
        params = json.loads(args["parameters_json"])
        return geo_tools.run_algorithm(args["algorithm_id"], _resolve_params(params))
    if name == "make_map":
        out = geo_tools.out_path(args.get("filename") or "karte.html")
        return {"map": geo_tools.write_map([geo_tools.find_path(f) for f in args["geojson_files"]], out)}
    if name == "geocode":
        return impact_tools.geocode(args["place"])
    if name == "traffic_impact":
        return impact_tools.traffic_impact(args["lat"], args["lon"], radius_m=args.get("radius_m"),
                                           closure_m=args.get("closure_m"), annahmen=args.get("annahmen"))
    if name == "construction_noise":
        return impact_tools.construction_noise(args["lat"], args["lon"], activity=args.get("activity") or "normal",
                                               annahmen=args.get("annahmen"))
    if name == "starkregen":
        return climate_tools.starkregen(args["lat"], args["lon"], radius_m=args.get("radius_m") or 50,
                                        massnahme=args.get("massnahme") or "versiegeln",
                                        niederschlag_mm=args.get("niederschlag_mm"), annahmen=args.get("annahmen"))
    if name == "hitze":
        return climate_tools.hitze(args["lat"], args["lon"], radius_m=args.get("radius_m") or 50,
                                   massnahme=args.get("massnahme") or "baeume_faellen", annahmen=args.get("annahmen"))
    if name == "ladesaeulen":
        return ladeinfra_tools.ladesaeulen(args["lat"], args["lon"], radius_m=args.get("radius_m") or 1500,
                                           e_auto_anteil=args.get("e_auto_anteil") or 0.15,
                                           anzahl=int(args.get("anzahl") or 10), annahmen=args.get("annahmen"))
    raise ValueError(f"Unbekanntes Tool: {name}")


# ---------- Agenten-Kern: liefert jeden Schritt als Ereignis (für Terminal, Streamlit, Log) ----------
def _with_retry(call, is_retryable, attempts=6):
    """Ruft das LLM auf, bei Überlastung/Rate-Limit mit Neuversuch.
    Generator: liefert 'retry'-Ereignisse, gibt am Ende (antwort, sekunden) zurück."""
    for i in range(attempts):
        start = time.time()
        try:
            return call(), time.time() - start
        except Exception as err:
            code = is_retryable(err)
            if not code or i == attempts - 1:
                raise
            wait = min(5 * 2 ** i, 60)
            yield {"type": "retry", "code": code, "wait": wait}
            time.sleep(wait)


def _run_tool(name, args, skills=True):
    yield {"type": "tool_call", "name": name, "args": args}
    start = time.time()
    try:
        result = {"result": execute_tool(name, args, skills)}
    except Exception as err:
        result = {"error": str(err)}
    yield {"type": "tool_result", "name": name, "result": result, "seconds": time.time() - start}
    return result


class BaseAgent:
    """Gemeinsamer Teil: Protokoll-Datei + Fehlerbehandlung. Anbieter-spezifisch ist nur _run()."""
    label = ""

    def __init__(self):
        log_dir = os.path.join(geo_tools.OUT, "logs")
        os.makedirs(log_dir, exist_ok=True)
        self.log_path = os.path.join(log_dir, time.strftime("session_%Y-%m-%d_%H-%M-%S.md"))
        self._log(f"# Geo-Agent Sitzung {time.strftime('%d.%m.%Y %H:%M')}\n\nModell: `{self.label}`\n")

    def _log(self, text):
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(text + "\n")

    def _log_event(self, ev):
        t = ev["type"]
        if t == "thought":
            self._log("> **Denkprozess:** " + ev["text"].strip().replace("\n", "\n> ") + "\n")
        elif t == "text":
            self._log(f"**Agent:** {ev['text']}\n")
        elif t == "llm_time":
            self._log(f"*(LLM: {ev['seconds']:.1f}s)*\n")
        elif t == "tool_call":
            self._log(f"**Werkzeug** `{ev['name']}`\n```json\n{json.dumps(ev['args'], ensure_ascii=False, indent=2)}\n```")
        elif t == "tool_result":
            self._log(f"Ergebnis ({ev['seconds']:.1f}s):\n```json\n{json.dumps(ev['result'], ensure_ascii=False)[:3000]}\n```\n")
        elif t == "retry":
            self._log(f"*({ev['code']}, neuer Versuch in {ev['wait']}s)*\n")
        elif t in ("error", "info"):
            self._log(f"**{t.upper()}:** {ev['text']}\n")

    def ask(self, prompt):
        """Generator: beantwortet eine Frage und liefert unterwegs alle Schritte als Ereignisse.
        Alle Dateien der Frage landen in einem eigenen Ordner output/ergebnisse/<Zeit>_<Frage>/ (self.run_dir),
        dort steht auch frage.md mit Frage, Antwort und genutzten Werkzeugen."""
        self._log(f"\n---\n\n## Frage: {prompt}\n")
        self.run_dir = geo_tools.new_run(prompt)
        texts, tools = [], []
        try:
            for ev in self._run(prompt):
                self._log_event(ev)
                if ev["type"] == "text":
                    texts.append(ev["text"])
                elif ev["type"] == "tool_call":
                    tools.append(f"- `{ev['name']}` {json.dumps(ev['args'], ensure_ascii=False)[:300]}")
                yield ev
        except Exception as err:
            ev = {"type": "error", "text": self._error_text(err)}
            self._log_event(ev)
            texts.append(f"**Fehler:** {ev['text']}")
            yield ev
        finally:
            if not os.path.isdir(self.run_dir):  # Frage ohne Dateien (z.B. reine Nachfrage): kein Ordner
                self.run_dir = None
                return
            with open(os.path.join(self.run_dir, "frage.md"), "w", encoding="utf-8") as f:
                f.write(f"# {prompt}\n\n{time.strftime('%d.%m.%Y %H:%M')} · Modell `{self.label}`\n\n"
                        "## Antwort\n\n" + ("\n\n".join(texts) or "(keine)") +
                        "\n\n## Werkzeuge\n\n" + ("\n".join(tools) or "(keine)") + "\n")

    def _run(self, prompt):
        raise NotImplementedError

    def _error_text(self, err):
        return f"Fehler: {err}"

    # ---------- Gesprächskontext speichern/laden (für gespeicherte Chats, siehe chat_store.py) ----------
    def export_state(self):
        """Kompletter LLM-Kontext als JSON-fähiges dict."""
        raise NotImplementedError

    def import_state(self, state):
        """Kontext aus export_state() wiederherstellen (nur gleicher Anbieter + Modell)."""
        raise NotImplementedError

    def import_transcript(self, turns):
        """Notlösung bei Modellwechsel: nur Fragen und Antworten als Text in den Kontext legen."""
        raise NotImplementedError

    @staticmethod
    def _answer_text(turn):
        return "\n\n".join(e["text"] for e in turn.get("events", []) if e.get("type") == "text") or "(keine Antwort)"


class GeminiAgent(BaseAgent):
    def __init__(self, api_key, model=GEMINI_MODEL, skills=True):
        self.label = f"gemini / {model}"
        self.choice = f"gemini:{model}"  # Schlüssel für model_choices / create_agent
        self.model = model
        self.skills = skills
        super().__init__()
        self.config = self._make_config()
        self.client = genai.Client(api_key=api_key)  # Client behalten, sonst wird er sofort geschlossen
        self.chat = self.client.chats.create(model=model, config=self.config)

    def _make_config(self):
        return types.GenerateContentConfig(
            system_instruction=system_prompt(self.skills),
            tools=[types.Tool(function_declarations=[
                types.FunctionDeclaration(name=t["name"], description=t["description"],
                                          parameters_json_schema=t["schema"])
                for t in tools_for(self.skills)])],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            thinking_config=types.ThinkingConfig(include_thoughts=True),  # Denkprozess mitliefern
        )

    def set_skills(self, skills):
        """Modus wechseln (mit/ohne eigene Analyse-Skills), Gesprächsverlauf bleibt erhalten."""
        if skills == self.skills:
            return
        self.skills = skills
        history = self.chat.get_history()
        self.config = self._make_config()
        self.chat = self.client.chats.create(model=self.model, config=self.config, history=history)
        self._log(f"\n*Modus: {'Skills + Datenquellen' if skills else 'Nur Datenquellen'}*\n")

    def export_state(self):
        # model_dump_json kodiert Binärdaten (z.B. thought_signature) korrekt als Base64
        return {"provider": "gemini", "model": self.model, "skills": self.skills,
                "history": [json.loads(c.model_dump_json(exclude_none=True)) for c in self.chat.get_history()]}

    def import_state(self, state):
        history = [types.Content.model_validate_json(json.dumps(c)) for c in state.get("history", [])]
        self.chat = self.client.chats.create(model=self.model, config=self.config, history=history)

    def import_transcript(self, turns):
        history = []
        for turn in turns:
            history.append(types.Content(role="user", parts=[types.Part(text=turn["prompt"])]))
            history.append(types.Content(role="model", parts=[types.Part(text=self._answer_text(turn))]))
        self.chat = self.client.chats.create(model=self.model, config=self.config, history=history)

    @staticmethod
    def _retryable(err):
        if isinstance(err, errors.ServerError) or (isinstance(err, errors.ClientError) and err.code == 429):
            return f"Google {err.code}"
        return None

    def _send(self, message):
        return (yield from _with_retry(lambda: self.chat.send_message(message), self._retryable))

    def _run(self, prompt):
        response, secs = yield from self._send(prompt)
        for _ in range(MAX_STEPS):
            yield {"type": "llm_time", "seconds": secs}
            content = response.candidates[0].content if response.candidates else None
            for p in (content.parts or []) if content else []:
                if p.text and p.thought:
                    yield {"type": "thought", "text": p.text}
                elif p.text and p.text.strip():
                    yield {"type": "text", "text": p.text}
            calls = response.function_calls or []
            if not calls:
                return
            replies = []
            for call in calls:
                result = yield from _run_tool(call.name, dict(call.args or {}), self.skills)
                replies.append(types.Part.from_function_response(name=call.name, response=result))
            response, secs = yield from self._send(replies)
        yield {"type": "info", "text": f"Abgebrochen nach {MAX_STEPS} Werkzeug-Runden."}

    def _error_text(self, err):
        if isinstance(err, errors.ClientError):
            if err.code == 429:
                return "Gratis-Kontingent bei Google aufgebraucht. Links ein anderes Modell wählen oder später nochmal versuchen."
            if err.code == 404:
                return f"Modell '{self.model}' nicht verfügbar: {err.message}. Links in der Seitenleiste ein anderes Modell wählen."
            return f"Gemini-Fehler ({err.code}): {err.message}"
        if isinstance(err, errors.ServerError):
            return f"Google-Server-Fehler ({err.code}) auch nach mehreren Versuchen. Frage bitte neu stellen."
        return f"Fehler: {err}"


class OpenRouterAgent(BaseAgent):
    """OpenRouter spricht das OpenAI-Format; darüber sind hunderte Modelle erreichbar (viele mit ':free')."""

    def __init__(self, api_key, model=OPENROUTER_MODEL, skills=True):
        self.label = f"openrouter / {model}"
        self.choice = f"openrouter:{model}"
        self.model = model
        self.skills = skills
        super().__init__()
        self.client = openai.OpenAI(api_key=api_key, base_url="https://openrouter.ai/api/v1", max_retries=0,
                                    default_headers={"X-Title": "Geo-Agent TU Darmstadt"})
        self._set_tools()
        self.messages = [{"role": "system", "content": system_prompt(self.skills)}]

    def _set_tools(self):
        self.tools = [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                                        "parameters": t["schema"]}} for t in tools_for(self.skills)]

    def set_skills(self, skills):
        """Modus wechseln (mit/ohne eigene Analyse-Skills), Gesprächsverlauf bleibt erhalten."""
        if skills == self.skills:
            return
        self.skills = skills
        self._set_tools()
        self.messages[0] = {"role": "system", "content": system_prompt(skills)}
        self._log(f"\n*Modus: {'Skills + Datenquellen' if skills else 'Nur Datenquellen'}*\n")

    def export_state(self):
        return {"provider": "openrouter", "model": self.model, "skills": self.skills, "messages": self.messages[1:]}

    def import_state(self, state):
        # Systemprompt immer aktuell lassen, nur den Gesprächsverlauf übernehmen
        self.messages = [{"role": "system", "content": system_prompt(self.skills)}] + [
            m for m in state.get("messages", []) if m.get("role") != "system"]

    def import_transcript(self, turns):
        self.messages = [{"role": "system", "content": system_prompt(self.skills)}]
        for turn in turns:
            self.messages += [{"role": "user", "content": turn["prompt"]},
                              {"role": "assistant", "content": self._answer_text(turn)}]

    @staticmethod
    def _retryable(err):
        if isinstance(err, openai.RateLimitError):
            return "OpenRouter 429 (Rate-Limit)"
        if isinstance(err, openai.APIStatusError) and err.status_code >= 500:
            return f"OpenRouter {err.status_code}"
        if isinstance(err, openai.APIConnectionError):
            return "Verbindungsfehler"
        return None

    def _complete(self):
        def call():
            resp = self.client.chat.completions.create(
                model=self.model, messages=self.messages, tools=self.tools,
                extra_body={"reasoning": {"enabled": True}},  # Denkprozess mitliefern
            )
            if not resp.choices:  # OpenRouter meldet Fehler des Modell-Anbieters manchmal im Body
                raise RuntimeError(f"Leere Antwort von OpenRouter: {(resp.model_extra or {}).get('error')}")
            return resp
        # Gratis-Modelle sind oft minutenlang überlastet: nach 2 Wiederholungen aufgeben (Hinweis: anderes Modell wählen)
        attempts = 3 if self.model.endswith(":free") or self.model.startswith("openrouter/") else 6
        return (yield from _with_retry(call, self._retryable, attempts=attempts))

    def _run(self, prompt):
        self.messages.append({"role": "user", "content": prompt})
        for _ in range(MAX_STEPS):
            resp, secs = yield from self._complete()
            yield {"type": "llm_time", "seconds": secs}
            msg = resp.choices[0].message
            reasoning = (msg.model_extra or {}).get("reasoning")
            if reasoning:
                yield {"type": "thought", "text": reasoning}
            if msg.content and msg.content.strip():
                yield {"type": "text", "text": msg.content}
            # komplette Antwort (inkl. reasoning_details) in den Verlauf, damit das Modell weiß, was es tat
            self.messages.append(msg.model_dump(exclude_none=True))
            if not msg.tool_calls:
                return
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError as err:
                    result = {"error": f"Ungültiges JSON in den Argumenten: {err}"}
                    yield {"type": "tool_result", "name": tc.function.name, "result": result, "seconds": 0.0}
                else:
                    result = yield from _run_tool(tc.function.name, args, self.skills)
                self.messages.append({"role": "tool", "tool_call_id": tc.id,
                                      "content": json.dumps(result, ensure_ascii=False)})
        yield {"type": "info", "text": f"Abgebrochen nach {MAX_STEPS} Werkzeug-Runden."}

    def _error_text(self, err):
        if isinstance(err, openai.AuthenticationError):
            return "OpenRouter-Key ungültig. Bitte OPENROUTER_API_KEY in .env prüfen."
        if isinstance(err, openai.RateLimitError):
            return ("Gratis-Modell gerade überlastet oder Tageslimit erreicht (OpenRouter 429). Links in der "
                    "Seitenleiste ein anderes Modell wählen und die Frage nochmal stellen, oder später erneut versuchen.")
        if isinstance(err, openai.NotFoundError):
            return (f"Modell '{self.model}' nicht gefunden oder durch Datenschutz-Einstellung gesperrt: {err.message}. "
                    "Für ':free'-Modelle unter openrouter.ai/settings/privacy die Gratis-Modelle erlauben.")
        if isinstance(err, openai.APIStatusError):
            return f"OpenRouter-Fehler ({err.status_code}): {err.message}"
        return f"Fehler: {err}"


def _key(name):
    key = os.environ.get(name, "")
    return "" if "HIER_EINTRAGEN" in key else key


OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
OPENROUTER_MODELS_CACHE = os.path.join(geo_tools.CACHE_DIR, "openrouter_free_models.json")


def openrouter_free_models(max_age_h=24):
    """Kostenlose OpenRouter-Modelle, die Werkzeuge (Tool-Calls) können - live von OpenRouter (ohne Key),
    einen Tag zwischengespeichert. Bei Fehler: alter Cache, sonst die festen Presets.
    -> [{"id", "name", "context"}], größter Kontext zuerst."""
    fresh = os.path.exists(OPENROUTER_MODELS_CACHE) and \
        time.time() - os.path.getmtime(OPENROUTER_MODELS_CACHE) < max_age_h * 3600
    if not fresh:
        try:
            req = urllib.request.Request(OPENROUTER_MODELS_URL, headers={"User-Agent": "uni-qgis-prototype"})
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.load(r)["data"]
            models = []
            for m in data:
                price = m.get("pricing") or {}
                free = m["id"].endswith(":free") or (price.get("prompt") == "0" and price.get("completion") == "0")
                if free and "tools" in (m.get("supported_parameters") or []):
                    models.append({"id": m["id"], "name": m.get("name", m["id"]), "context": m.get("context_length") or 0})
            models.sort(key=lambda m: (-m["context"], m["id"]))
            os.makedirs(geo_tools.CACHE_DIR, exist_ok=True)
            with open(OPENROUTER_MODELS_CACHE, "w", encoding="utf-8") as f:
                json.dump(models, f, ensure_ascii=False)
            return models
        except Exception as err:
            print(f"  OpenRouter-Modellliste nicht abrufbar ({err}), nutze Cache/Presets")
    if os.path.exists(OPENROUTER_MODELS_CACHE):
        with open(OPENROUTER_MODELS_CACHE, encoding="utf-8") as f:
            return json.load(f)
    return [{"id": m, "name": m, "context": 0} for p, m in PRESETS.values() if p == "openrouter"]


def model_choices():
    """Alle wählbaren Modelle für die Oberfläche: [(auswahl, anzeigename)].
    auswahl = 'gemini:<modell>' bzw. 'openrouter:<modell>', geht direkt an create_agent()."""
    choices = []
    if _key("GEMINI_API_KEY"):
        choices += [(f"gemini:{m}", f"Google · {m}") for p, m in PRESETS.values() if p == "gemini"]
    if _key("OPENROUTER_API_KEY"):
        for m in openrouter_free_models():
            ctx = f" · {m['context'] // 1000}k" if m["context"] else ""
            choices.append((f"openrouter:{m['id']}", f"OpenRouter · {m['name'].replace(' (free)', '')}{ctx}"))
    return choices


def default_choice():
    """Modell aus .env (MODEL=<kurzname>) als Auswahl-Schlüssel."""
    preset = (os.environ.get("MODEL") or DEFAULT_PRESET).strip().lower()
    provider, model = PRESETS.get(preset, PRESETS[DEFAULT_PRESET])
    return f"{provider}:{model}"


def create_agent(preset=None, skills=True):
    """Baut den Agenten. preset: Kurzname aus PRESETS (z.B. 'gemma'), 'openrouter:<modell-id>' bzw.
    'gemini:<modell-id>' (aus model_choices), ohne Angabe MODEL aus .env. Wirft ValueError mit verständlicher Meldung.
    skills=False: Modus 'Nur Datenquellen' (ohne eigene Analyse-Werkzeuge wie hitze/starkregen)."""
    preset = (preset or os.environ.get("MODEL") or DEFAULT_PRESET).strip()
    if preset.split(":", 1)[0] in ("gemini", "openrouter") and ":" in preset:
        provider, model = preset.split(":", 1)
    elif preset.lower() in PRESETS:
        provider, model = PRESETS[preset.lower()]
    else:
        raise ValueError(f"Unbekanntes MODEL '{preset}' in .env. Erlaubt: {', '.join(PRESETS)}.")
    if provider == "gemini":
        key = _key("GEMINI_API_KEY")
        if not key:
            raise ValueError("GEMINI_API_KEY fehlt in .env (Key von aistudio.google.com/apikey).")
        return GeminiAgent(key, model, skills)
    key = _key("OPENROUTER_API_KEY")
    if not key:
        raise ValueError("OPENROUTER_API_KEY fehlt in .env (Key von openrouter.ai/keys).")
    return OpenRouterAgent(key, model, skills)


# ---------- Terminal-Version ----------
DIM, RESET = "\033[2m", "\033[0m"


def main():
    try:
        agent = create_agent()
    except ValueError as err:
        sys.exit(str(err))
    print(f"Geo-Agent ({agent.label}). Frag z.B.: 'Wo in Darmstadt rund um die TU fehlen Ladesäulen?'  ('exit' zum Beenden)")
    print(f"Protokoll mit Denkprozess: {agent.log_path}")
    while True:
        try:
            prompt = input("\nDu: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if prompt.lower() in ("exit", "quit"):
            break
        if not prompt:
            continue
        for ev in agent.ask(prompt):
            t = ev["type"]
            if t == "thought":
                print(f"{DIM}  [denkt] {ev['text'].strip()}{RESET}")
            elif t == "text":
                print(f"\nAgent: {ev['text']}")
            elif t == "llm_time":
                print(f"{DIM}  (LLM: {ev['seconds']:.1f}s){RESET}")
            elif t == "tool_call":
                print(f"  -> {ev['name']}({json.dumps(ev['args'], ensure_ascii=False)[:200]})")
            elif t == "tool_result":
                err = ev["result"].get("error")
                print(f"{DIM}     fertig in {ev['seconds']:.1f}s{RESET}" + (f"  FEHLER: {err}" if err else ""))
            elif t == "retry":
                print(f"{DIM}     ({ev['code']}: überlastet/Limit, neuer Versuch in {ev['wait']}s ...){RESET}")
            else:
                print(f"\n[{ev['text']}]")


if __name__ == "__main__":
    main()
