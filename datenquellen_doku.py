"""
Doku der freien Datenquellen: Gruppen, Kurztexte und Exporte. Ohne Streamlit nutzbar.

Die Seite "Datenquellen" (datenquellen_page.py) zeigt daraus die Doku an und bietet die Exporte zum Download:
  export_markdown(gruppierung)  -> .md   (GitHub, Obsidian, Bericht)
  export_html(gruppierung)      -> .html (eigenständige Seite: im Browser öffnen, teilen, als PDF drucken)
  export_csv()                  -> .csv  (eine Zeile je Quelle, Semikolon + UTF-8 mit BOM: öffnet direkt in Excel)
  export_json()                 -> .json (alle Felder, maschinenlesbar)
  export_pdf(gruppierung)       -> .pdf  (die HTML-Seite, gedruckt von Edge/Chrome ohne Fenster)
Die Exporte enthalten nur die Quellen, keine Beispielaufrufe oder -antworten (die stehen in der App unter "Details").

Ohne Oberfläche:
  python datenquellen_doku.py [ordner] [Thema|Anbieter|Anbindung|Art]   -> schreibt alle Formate (Standard: output/doku)
"""
import csv
import datetime
import functools
import html
import io
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlparse

import datenquellen as dq

GRUPPIERUNGEN = ["Thema", "Anbieter", "Anbindung", "Art"]

KAT_INFO = {
    dq.K_WETTER: ("🌦️", "Messwerte, Vorhersagen, Klima seit 1940 und bis 2050, Warnungen, Starkregen-Bemessung, "
                       "Wärmeinsel und Hitze."),
    dq.K_LUFT: ("💨", "Luftqualität von amtlichen Stationen, aus Modellen und von Bürgersensoren, dazu Pollen und UV."),
    dq.K_WASSER: ("🌊", "Pegel, Abflussvorhersage, Hochwasser- und Starkregen-Gefahrenkarten."),
    dq.K_UMWELT: ("🌳", "Lärm, Schutzgebiete, Wasserschutz, Biotope, Boden, Geologie, Radon und Artenfunde."),
    dq.K_BEV: ("👥", "Verwaltungsgrenzen, Zensus, Ladesäulen, Kraftwerke und Strommix."),
    dq.K_FERN: ("🛰️", "Versiegelung, Bäume, Landbedeckung, Vegetation und Oberflächentemperatur aus Satellitendaten, "
                     "dazu Geländehöhe und Luftbild."),
    dq.K_MOB: ("🚆", "ÖPNV mit Echtzeit, Erreichbarkeit, Routen, Autobahn-Meldungen, Leihräder und Unfälle."),
    dq.K_WISSEN: ("📖", "Wikipedia-Artikel und Wikidata-Objekte in der Nähe."),
    dq.K_KAT: ("🗂️", "Open-Data-Kataloge durchsuchen und beliebige Dateien, WFS-, WMS- und ArcGIS-Dienste laden."),
}
ART_INFO = {  # art: (Symbol, Name, was der Aufruf braucht)
    "punkt": ("📍", "Punkt", "Wert am Ort: braucht lat und lon."),
    "umkreis": ("⭕", "Umkreis", "Daten im Radius um den Ort: lat, lon und optional radius_m. Meist mit Karte."),
    "global": ("🌐", "Ohne Ort", "Gilt für ganz Deutschland, ohne lat/lon."),
    "suche": ("🔎", "Suche", "Kataloge und beliebige Dateien/Dienste, gesteuert über parameter."),
}
ANBINDUNG_INFO = {
    "api": ("🔌", "Direkte Abfrage einer JSON- oder REST-Schnittstelle."),
    "arcgis": ("🗺️", "Abfrage von ArcGIS-MapServer/ImageServer (query, identify, exportImage), Antwort als GeoJSON."),
    "wms": ("🖼️", "Kartendienst: Wert am Punkt (GetFeatureInfo) oder Kartenbild (GetMap)."),
    "wfs": ("📦", "Geodaten über WFS, geladen mit ogr2ogr aus der QGIS-Installation."),
    "gdal": ("🛰️", "Rasterdaten aus dem Netz (Cloud-GeoTIFF, NetCDF), gelesen mit GDAL aus der QGIS-Installation."),
    "datei": ("📥", "Download-Dateien von Open-Data-Servern (ZIP, ESRI-ASCII-Raster, CSV), zwischengespeichert."),
    "katalog": ("🔎", "Suche in Open-Data-Katalogen (CKAN, Mapbender)."),
    "lokal": ("💾", "Einmal geladene Daten im Projektordner (data/)."),
}
ANBIETER_GRUPPEN = [  # (Stichwort im Anbieter, Gruppe) - erster Treffer zählt
    ("Wetterdienst", "Deutscher Wetterdienst (DWD)"),
    ("HLNUG", "HLNUG Hessen"), ("Hessisches Landesamt", "HLNUG Hessen"),
    ("Open-Meteo", "Open-Meteo"),
    ("Copernicus", "Copernicus, ESA und USGS"), ("Europäische", "Copernicus, ESA und USGS"),
    ("USGS", "Copernicus, ESA und USGS"),
    ("Hessische Verwaltung", "Land Hessen und Stadt Darmstadt"), ("Geoportal Hessen", "Land Hessen und Stadt Darmstadt"),
    ("Darmstadt", "Land Hessen und Stadt Darmstadt"),
    ("je nach", "Beliebige Dienste (Adresse als Parameter)"),
    ("sensor.community", "Offene Projekte und Communitys"), ("openSenseMap", "Offene Projekte und Communitys"),
    ("Biodiversity", "Offene Projekte und Communitys"), ("CityBikes", "Offene Projekte und Communitys"),
    ("Transitous", "Offene Projekte und Communitys"), ("FOSSGIS", "Offene Projekte und Communitys"),
    ("Wikimedia", "Offene Projekte und Communitys"),
]
ANBIETER_INFO = {
    "Deutscher Wetterdienst (DWD)": "Open-Data-Server, GeoServer und Bright Sky (JSON-Zugang zu den DWD-Daten).",
    "HLNUG Hessen": "Hessisches Landesamt für Naturschutz, Umwelt und Geologie: ArcGIS-Dienste der Umweltkarten.",
    "Open-Meteo": "Freie Wetter-API (Vorhersage, ERA5, CMIP6, CAMS, GloFAS, Geländehöhe).",
    "Bund: Behörden, Ämter, Portale": "UBA, BBK, BfN, BKG, Bundesnetzagentur, Statistikämter, Autobahn GmbH, WSV, GovData.",
    "Copernicus, ESA und USGS": "Satellitendaten und europäische Landbedeckung.",
    "Offene Projekte und Communitys": "Wikimedia, GBIF, Transitous, Valhalla (FOSSGIS), Bürgersensoren, CityBikes.",
    "Land Hessen und Stadt Darmstadt": "Luftbild und Liegenschaftskarte (HVBG), Geoportal Hessen, Open Data Darmstadt.",
    "Beliebige Dienste (Adresse als Parameter)": "Allgemeine Werkzeuge für Dienste und Dateien, die (noch) nicht im "
                                                 "Katalog stehen.",
}
ANBIETER_KURZ = [  # lange Behördennamen für Tabellen abkürzen
    ("Hessisches Landesamt für Naturschutz, Umwelt und Geologie (HLNUG)", "HLNUG"),
    ("Deutscher Wetterdienst", "DWD"), ("Bundesnetzagentur", "BNetzA"),
    ("Europäische Umweltagentur / Copernicus Land Monitoring Service", "EEA / Copernicus"),
    ("Europäische Weltraumorganisation (ESA)", "ESA"),
    ("Wasserstraßen- und Schifffahrtsverwaltung des Bundes", "WSV (Bund)"),
    ("Bundesamt für Bevölkerungsschutz", "BBK"), ("Bundesamt für Kartographie und Geodäsie", "BKG"),
    ("Bundesamt für Naturschutz", "BfN"), ("Bundesamt für Strahlenschutz", "BfS"), ("Umweltbundesamt", "UBA"),
    ("Global Biodiversity Information Facility", "GBIF"), ("Statistisches Bundesamt (Destatis)", "Destatis"),
    ("Hessische Verwaltung für Bodenmanagement und Geoinformation", "HVBG Hessen"),
    ("Statistische Ämter des Bundes und der Länder", "Statistische Ämter"),
    ("Die Autobahn GmbH des Bundes", "Autobahn GmbH"), ("Wissenschaftsstadt Darmstadt", "Stadt Darmstadt"),
    (" mit Fahrplänen von DELFI u.a.", ""), ("Earth Search ", ""),
]
ARGUMENTE = [  # Argumente des Werkzeugs datenquelle_abfragen
    ("quelle", "ID der Quelle (Pflicht)"),
    ("lat, lon", "Ort in WGS84, bei Punkt- und Umkreis-Quellen Pflicht (vorher mit geocode bestimmen)"),
    ("radius_m", "nur bei Umkreis-Quellen, sonst ignoriert; wird auf das Maximum der Quelle begrenzt"),
    ("parameter", "quellenspezifisch, siehe jeweilige Quelle"),
]
ANTWORT = [  # Felder jeder Antwort
    ("quelle", "Metadaten: id, name, anbieter, lizenz, url, stand (Datum der Daten)"),
    ("radius_m", "nur bei Umkreis-Quellen"),
    ("zusammenfassung", "die eigentlichen Daten, kompakt für das LLM"),
    ("files", "GeoJSON (EPSG:4326, mit Farben und Popups) oder Bild im Ergebnisordner, für make_map und QGIS"),
    ("sekunden", "Dauer der Abfrage"),
]
TITEL = "Freie Datenquellen des Geo-Agenten"


# =====================================================================================================
# Gemeinsame Helfer (Seite und Exporte)
# =====================================================================================================
@functools.lru_cache(maxsize=None)
def technik(qid):
    """(Anbindung, Dienst-Adressen) aus dem Code der Quelle."""
    return dq.anbindung(qid), tuple(dq.endpunkte(qid))


def anbieter_gruppe(q):
    return next((g for stichwort, g in ANBIETER_GRUPPEN if stichwort in q["anbieter"]), "Bund: Behörden, Ämter, Portale")


def anbieter_kurz(text):
    for lang, kurz_ in ANBIETER_KURZ:
        text = text.replace(lang, kurz_)
    return text


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
                  .replace("ß", "ss")).strip("-")


def datum(iso):
    """2026-11-02 -> 02.11.2026"""
    teile = str(iso or "").split("-")
    return f"{teile[2]}.{teile[1]}.{teile[0]}" if len(teile) == 3 else str(iso)


def kurz(obj, n_list=3, n_str=220):
    """Beispielantwort für die Anzeige kürzen: Listen auf wenige Einträge, lange Texte abschneiden."""
    if isinstance(obj, dict):
        return {k: kurz(v, n_list, n_str) for k, v in obj.items()}
    if isinstance(obj, list):
        rest = [v for v in obj if isinstance(v, str) and v.startswith("... und ")]  # Hinweis aus abfragen()
        echte = [v for v in obj if v not in rest]
        out = [kurz(v, n_list, n_str) for v in echte[:n_list]]
        mehr = len(echte) - n_list + sum(int(re.sub(r"\D", "", v) or 0) for v in rest)
        if mehr > 0:
            out.append(f"… und {mehr} weitere")
        return out
    if isinstance(obj, str) and len(obj) > n_str:
        return obj[:n_str] + " …"
    return obj


def gruppen(gruppierung="Thema", such=None):
    """{Gruppe: [ids]} in sinnvoller Reihenfolge, gefiltert nach Suchwörtern."""
    woerter = (such or "").lower().split()
    out = {}
    for qid, q in dq.QUELLEN.items():
        anb, endp = technik(qid)
        kurz_, worte = dq.kurzinfo(qid)
        text = " ".join([qid, q["name"], q["beschreibung"], q["anbieter"], q["kategorie"], " ".join(q["parameter"]),
                         dq.ANBINDUNGEN[anb], " ".join(endp), kurz_, " ".join(worte)]).lower()
        if not all(w in text for w in woerter):
            continue
        g = {"Thema": q["kategorie"], "Anbieter": anbieter_gruppe(q), "Anbindung": dq.ANBINDUNGEN[anb],
             "Art": ART_INFO[q["art"]][1]}[gruppierung]
        out.setdefault(g, []).append(qid)
    if gruppierung == "Thema":
        reihe = dq.KATEGORIEN
    elif gruppierung == "Anbindung":
        reihe = list(dq.ANBINDUNGEN.values())
    elif gruppierung == "Art":
        reihe = [v[1] for v in ART_INFO.values()]
    else:  # Anbieter: große Gruppen zuerst, beliebige Dienste zuletzt
        reihe = sorted(out, key=lambda g_: (g_.startswith("Beliebige"), -len(out[g_]), g_))
    return {g: out[g] for g in reihe if g in out}


def gruppen_info(gruppierung, g):
    """(Symbol, Beschreibung) einer Gruppe."""
    if gruppierung == "Thema":
        return KAT_INFO.get(g, ("📚", ""))
    if gruppierung == "Anbindung":
        key = next(k for k, v in dq.ANBINDUNGEN.items() if v == g)
        return ANBINDUNG_INFO[key]
    if gruppierung == "Art":
        s, _, text = next(v for v in ART_INFO.values() if v[1] == g)
        return s, text
    return "🏛️", ANBIETER_INFO.get(g, "")


def python_aufruf(aufruf):
    """Python-Code für einen Aufruf (gleiche Argumente wie das Werkzeug)."""
    args = ", ".join([json.dumps(aufruf["quelle"])] + [f"{k}={json.dumps(v, ensure_ascii=False)}"
                                                       for k, v in aufruf.items() if k != "quelle"])
    return f"import datenquellen\n\nres = datenquellen.abfragen({args})\nprint(res[\"zusammenfassung\"])"


def eintrag(qid):
    """Alle Doku-Felder einer Quelle als ein Dict (Grundlage aller Exporte, ohne Beispiele)."""
    q = dq.QUELLEN[qid]
    anb, endp = technik(qid)
    kurz_, worte = dq.kurzinfo(qid)
    return {
        "id": qid, "name": q["name"], "thema": q["kategorie"], "kurzbeschreibung": kurz_, "stichworte": worte,
        "beschreibung": q["beschreibung"], "art": ART_INFO[q["art"]][1], "anbindung": dq.ANBINDUNGEN[anb],
        "anbieter": q["anbieter"], "anbieter_gruppe": anbieter_gruppe(q), "lizenz": q["lizenz"],
        "webseite": q["url"] or None, "dienst_adressen": list(endp), "parameter": q["parameter"],
        "radius_standard_m": q["radius"] if q["art"] == "umkreis" else None,
        "radius_max_m": q["max_radius"] if q["art"] == "umkreis" else None,
    }


def _stand():
    return datetime.date.today().isoformat()


# =====================================================================================================
# Exporte
# =====================================================================================================
def export_json():
    daten = {
        "titel": TITEL, "stand": _stand(), "anzahl": len(dq.QUELLEN),
        "werkzeug": "datenquelle_abfragen", "argumente": dict(ARGUMENTE), "antwort_felder": dict(ANTWORT),
        "quellen": [eintrag(qid) for qid in dq.QUELLEN],
    }
    return json.dumps(daten, ensure_ascii=False, indent=2, default=str)


def export_csv():
    """Eine Zeile je Quelle; Semikolon und UTF-8 mit BOM, damit Excel (deutsch) Umlaute und Spalten erkennt."""
    spalten = [("ID", "id"), ("Name", "name"), ("Thema", "thema"), ("Kurzbeschreibung", "kurzbeschreibung"),
               ("Wofür / liefert", "stichworte"), ("Beschreibung", "beschreibung"), ("Art", "art"),
               ("Anbindung", "anbindung"), ("Anbieter", "anbieter"), ("Lizenz", "lizenz"), ("Webseite", "webseite"),
               ("Dienst-Adressen", "dienst_adressen"), ("Parameter", "parameter"),
               ("Radius Standard (m)", "radius_standard_m"), ("Radius max. (m)", "radius_max_m")]
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    w.writerow([titel for titel, _ in spalten])
    for qid in dq.QUELLEN:
        e = eintrag(qid)
        zeile = []
        for _, key in spalten:
            v = e[key]
            if key == "stichworte":
                v = ", ".join(v)
            elif key == "dienst_adressen":
                v = " | ".join(v)
            elif key == "parameter":
                v = " | ".join(f"{k}: {t}" for k, t in v.items())
            zeile.append("" if v is None else v)
        w.writerow(zeile)
    return ("﻿" + buf.getvalue()).encode("utf-8")


def _md(text):
    """Text für eine Markdown-Tabellenzelle."""
    return str(text).replace("|", "/").replace("\n", " ")


def _gruppenwort(gruppierung):
    return "Kategorien" if gruppierung == "Thema" else "Gruppen"


def _md_tabelle(ids):
    z = ["| Quelle | ID | Beschreibung | Wofür / liefert | Art | Anbieter |", "|---|---|---|---|---|---|"]
    for qid in ids:
        e = eintrag(qid)
        anb = anbieter_kurz(e["anbieter"])
        z.append(f"| [{_md(e['name'])}](#q-{qid}) | `{qid}` | {_md(e['kurzbeschreibung'])} | "
                 f"{_md(', '.join(e['stichworte']))} | {ART_INFO[dq.QUELLEN[qid]['art']][0]} {e['art']} | "
                 + (f"[{_md(anb)}]({e['webseite']}) |" if e["webseite"] else f"{_md(anb)} |"))
    return z + [""]


def export_markdown(gruppierung="Thema"):
    """Aufbau: 1. alle Kategorien als Tabellen nacheinander, 2. je Kategorie die Quellen mit kurzen Infos,
    3. wie ein Aufruf funktioniert."""
    gr = gruppen(gruppierung)
    n, wort = len(dq.QUELLEN), _gruppenwort(gruppierung)
    z = [f"# {TITEL}", "",
         f"Stand {datum(_stand())} · {n} Quellen ohne API-Key in {len(gr)} {wort} (nach {gruppierung}). "
         "Erzeugt aus `datenquellen.py` (Seite *Datenquellen* im Geo-Agenten).", "",
         f"Inhalt: [Alle {wort} im Überblick](#ueberblick) · [Quellen je Kategorie](#details) · "
         "[So funktioniert ein Aufruf](#aufruf)", "",
         '<a id="ueberblick"></a>', "", f"## Alle {wort} im Überblick", ""]
    for g, ids in gr.items():
        symbol, info = gruppen_info(gruppierung, g)
        z += [f"### [{symbol} {g}](#{slug(g)}) ({len(ids)})", ""] + ([info, ""] if info else []) + _md_tabelle(ids)
    z += ['<a id="details"></a>', "", "## Quellen je Kategorie", ""]
    for g, ids in gr.items():
        symbol, info = gruppen_info(gruppierung, g)
        z += [f'<a id="{slug(g)}"></a>', "", f"### {symbol} {g}", ""] + ([info, ""] if info else [])
        for qid in ids:
            z += _md_quelle(eintrag(qid))
    z += ['<a id="aufruf"></a>', "", "## So funktioniert ein Aufruf", "",
          "Der Agent nutzt **ein** Werkzeug für alle Quellen: `datenquelle_abfragen`.", "",
          "| Argument | Bedeutung |", "|---|---|", *[f"| `{a}` | {_md(t)} |" for a, t in ARGUMENTE], "",
          "Jede Antwort ist gleich aufgebaut:", "",
          "| Feld | Inhalt |", "|---|---|", *[f"| `{a}` | {_md(t)} |" for a, t in ANTWORT], "",
          "Arten: " + " · ".join(f"{s} **{name}**: {text}" for s, name, text in ART_INFO.values()), "",
          "Ohne Agent: in Python `datenquellen.abfragen(...)` oder `python datenquellen.py test <quelle>`.", ""]
    return "\n".join(z) + "\n"


def _md_quelle(e):
    qid = e["id"]
    q = dq.QUELLEN[qid]
    z = [f'<a id="q-{qid}"></a>', "", f"#### {e['name']} · `{qid}`", "", e["beschreibung"], ""]
    art = f"{ART_INFO[q['art']][0]} {e['art']}"
    if e["radius_standard_m"]:
        art += f" (Standard {e['radius_standard_m']} m, max. {e['radius_max_m']} m)"
    z += [f"- **Wofür / liefert:** {', '.join(e['stichworte'])}",
          f"- **Art:** {art} · **Anbindung:** {e['anbindung']}",
          f"- **Anbieter:** {e['anbieter']} · **Lizenz:** {e['lizenz']}"]
    if e["webseite"]:
        z.append(f"- **Webseite / Doku:** [{urlparse(e['webseite']).netloc.removeprefix('www.')}]({e['webseite']})")
    if e["dienst_adressen"]:
        z.append("- **Dienst-Adresse" + ("n" if len(e["dienst_adressen"]) > 1 else "") + ":** " +
                 " · ".join(f"`{a}`" for a in e["dienst_adressen"]))
    z.append("")
    if e["parameter"]:
        z += ["| Parameter | Bedeutung |", "|---|---|",
              *[f"| `{k}` | {_md(t)} |" for k, t in e["parameter"].items()], ""]
    return z


HTML_CSS = """
:root { --text:#1f2328; --muted:#59636e; --line:#d1d9e0; --bg:#ffffff; --soft:#f6f8fa; --accent:#2f6fb0;
        --tag:#eef2f6; }
@media (prefers-color-scheme: dark) {
  :root { --text:#e6e8eb; --muted:#9aa4af; --line:#30363d; --bg:#0f1419; --soft:#161b22; --accent:#6ea8e0;
          --tag:#222a33; } }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--text);
       font:15px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; }
main { max-width:1180px; margin:0 auto; padding:32px 20px 64px; }
h1 { font-size:1.9rem; margin:0 0 4px; } h2 { margin:40px 0 6px; padding-bottom:6px; border-bottom:1px solid var(--line); }
h3 { margin:30px 0 6px; font-size:1.2rem; } h3 a { color:inherit; text-decoration:none; }
h4 { margin:12px 0 6px; font-size:1.02rem; }
a { color:var(--accent); } .muted { color:var(--muted); }
table { width:100%; border-collapse:collapse; margin:10px 0 18px; font-size:0.92rem; }
th, td { text-align:left; vertical-align:top; padding:7px 8px; border-bottom:1px solid var(--line); }
th { color:var(--muted); font-weight:600; }
table.quellen { table-layout:fixed; }
table.quellen th:nth-child(1){width:20%} table.quellen th:nth-child(2){width:16%} table.quellen th:nth-child(3){width:22%}
table.quellen th:nth-child(4){width:22%} table.quellen th:nth-child(5){width:8%} table.quellen th:nth-child(6){width:12%}
code { font-family:ui-monospace,Consolas,monospace; font-size:0.86em; background:var(--soft); padding:1px 4px;
       border-radius:4px; overflow-wrap:anywhere; }
table.kv td:first-child { white-space:nowrap; width:1%; }
pre { background:var(--soft); border:1px solid var(--line); border-radius:8px; padding:12px; overflow:auto;
      font-size:0.82rem; } pre code { background:none; padding:0; word-break:normal; }
.tag { display:inline-block; background:var(--tag); border-radius:6px; padding:0 6px; margin:1px 2px 1px 0;
       font-size:0.85em; }
.quelle { border:1px solid var(--line); border-radius:10px; padding:4px 18px 10px; margin:14px 0; }
.toc { columns:3; padding-left:18px; } details summary { cursor:pointer; color:var(--accent); }
@page { size:A4; margin:14mm 12mm; }
@media print {
  :root { --text:#1f2328; --muted:#59636e; --line:#d1d9e0; --bg:#ffffff; --soft:#f6f8fa; --accent:#1f2328;
          --tag:#eef2f6; }
  body { font-size:10pt; } main { max-width:none; padding:0; }
  h2.teil, h3.gruppe { break-before:page; } h2.teil + h3.gruppe { break-before:auto; }
  h2, h3, h4 { break-after:avoid; } tr { break-inside:avoid; } h3 { margin:16px 0 4px; }
  h1 { font-size:1.6rem; } h2 { margin:18px 0 4px; } th, td { padding:4px 6px; } table { margin:6px 0 10px; }
  table.quellen { font-size:8.5pt; } td { overflow-wrap:break-word; }
  table.kv { break-inside:avoid; }
  pre { white-space:pre-wrap; word-break:break-word; overflow:visible; font-size:7.5pt; }
  .quelle { border:none; border-top:1px solid var(--line); border-radius:0; padding:2px 0 6px; margin:10px 0; }
  a { color:inherit; text-decoration:none; } details summary { color:var(--muted); cursor:default; }
}
"""


def _h(text):
    return html.escape(str(text))


def _html_tabelle(ids):
    t = ["<table class='quellen'><tr><th>Quelle</th><th>ID</th><th>Beschreibung</th><th>Wofür / liefert</th>"
         "<th>Art</th><th>Anbieter</th></tr>"]
    for qid in ids:
        e = eintrag(qid)
        anb = _h(anbieter_kurz(e["anbieter"]))
        if e["webseite"]:
            anb = f"<a href='{_h(e['webseite'])}'>{anb}</a>"
        tags = "".join(f"<span class=tag>{_h(w)}</span>" for w in e["stichworte"])
        t.append(f"<tr><td><a href='#q-{qid}'><b>{_h(e['name'])}</b></a></td>"
                 f"<td><code>{qid.replace('_', '_<wbr>')}</code></td><td>{_h(e['kurzbeschreibung'])}</td>"
                 f"<td>{tags}</td><td>{ART_INFO[dq.QUELLEN[qid]['art']][0]} {_h(e['art'])}</td><td>{anb}</td></tr>")
    return "\n".join(t) + "</table>"


def export_html(gruppierung="Thema"):
    """Eigenständige HTML-Seite (auch Vorlage für das PDF). Aufbau wie export_markdown."""
    gr = gruppen(gruppierung)
    n, wort = len(dq.QUELLEN), _gruppenwort(gruppierung)
    t = [f"<!doctype html><html lang='de'><head><meta charset='utf-8'>"
         f"<meta name='viewport' content='width=device-width,initial-scale=1'><title>{_h(TITEL)}</title>"
         f"<style>{HTML_CSS}</style></head><body><main>",
         f"<h1>{_h(TITEL)}</h1><p class='muted'>Stand {datum(_stand())} · {n} Quellen ohne API-Key in {len(gr)} "
         f"{wort} (nach {_h(gruppierung)}). Erzeugt aus <code>datenquellen.py</code>.</p>",
         f"<p class='muted'>Inhalt: <a href='#ueberblick'>Alle {wort} im Überblick</a> · "
         "<a href='#details'>Quellen je Kategorie</a> · <a href='#aufruf'>So funktioniert ein Aufruf</a></p>",
         f"<h2 id='ueberblick'>Alle {wort} im Überblick</h2>"]
    for g, ids in gr.items():
        symbol, info = gruppen_info(gruppierung, g)
        t.append(f"<h3><a href='#{slug(g)}'>{symbol} {_h(g)}</a> <span class='muted'>({len(ids)})</span></h3>" +
                 (f"<p class='muted'>{_h(info)}</p>" if info else "") + _html_tabelle(ids))
    t.append("<h2 class='teil' id='details'>Quellen je Kategorie</h2>")
    for g, ids in gr.items():
        symbol, info = gruppen_info(gruppierung, g)
        t.append(f"<h3 class='gruppe' id='{slug(g)}'>{symbol} {_h(g)}</h3>" +
                 (f"<p class='muted'>{_h(info)}</p>" if info else ""))
        t += [_html_quelle(eintrag(qid)) for qid in ids]
    t += ["<h2 class='teil' id='aufruf'>So funktioniert ein Aufruf</h2><p>Der Agent nutzt <b>ein</b> Werkzeug für "
          "alle Quellen: <code>datenquelle_abfragen</code>.</p>",
          "<table class='kv'><tr><th>Argument</th><th>Bedeutung</th></tr>" +
          "".join(f"<tr><td><code>{_h(a)}</code></td><td>{_h(b)}</td></tr>" for a, b in ARGUMENTE) + "</table>",
          "<p>Jede Antwort ist gleich aufgebaut:</p><table class='kv'><tr><th>Feld</th><th>Inhalt</th></tr>" +
          "".join(f"<tr><td><code>{_h(a)}</code></td><td>{_h(b)}</td></tr>" for a, b in ANTWORT) + "</table>",
          "<p>" + " · ".join(f"{s} <b>{_h(name)}</b>: {_h(text)}" for s, name, text in ART_INFO.values()) + "</p>",
          "<p>Ohne Agent: in Python <code>datenquellen.abfragen(...)</code> oder "
          "<code>python datenquellen.py test &lt;quelle&gt;</code>.</p>",
          "</main></body></html>"]
    return "\n".join(t)


def _html_quelle(e):
    qid = e["id"]
    q = dq.QUELLEN[qid]
    art = f"{ART_INFO[q['art']][0]} {e['art']}"
    if e["radius_standard_m"]:
        art += f" (Standard {e['radius_standard_m']} m, max. {e['radius_max_m']} m)"
    zeilen = [f"<b>Wofür / liefert:</b> {''.join(f'<span class=tag>{_h(w)}</span>' for w in e['stichworte'])}",
              f"<b>Art:</b> {_h(art)} · <b>Anbindung:</b> {_h(e['anbindung'])}",
              f"<b>Anbieter:</b> {_h(e['anbieter'])} · <b>Lizenz:</b> {_h(e['lizenz'])}"]
    if e["webseite"]:
        zeilen.append(f"<b>Webseite / Doku:</b> <a href='{_h(e['webseite'])}'>"
                      f"{_h(urlparse(e['webseite']).netloc.removeprefix('www.'))}</a>")
    if e["dienst_adressen"]:
        zeilen.append("<b>Dienst-Adresse" + ("n" if len(e["dienst_adressen"]) > 1 else "") + ":</b> " +
                      " · ".join(f"<code>{_h(a)}</code>" for a in e["dienst_adressen"]))
    t = [f"<section class='quelle' id='q-{qid}'><h4>{_h(e['name'])} · <code>{qid}</code></h4>",
         f"<p>{_h(e['beschreibung'])}</p><p>" + "<br>".join(zeilen) + "</p>"]
    if e["parameter"]:
        t.append("<table class='kv'><tr><th>Parameter</th><th>Bedeutung</th></tr>" + "".join(
            f"<tr><td><code>{_h(k)}</code></td><td>{_h(v)}</td></tr>" for k, v in e["parameter"].items()) + "</table>")
    t.append("</section>")
    return "\n".join(t)


def browser_pfad():
    """Edge oder Chrome (für PDF). Eigener Pfad über die Umgebungsvariable PDF_BROWSER."""
    kandidaten = [os.environ.get("PDF_BROWSER"),
                  r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                  r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
                  r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                  r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                  os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google", "Chrome", "Application", "chrome.exe"),
                  *(shutil.which(n) for n in ("msedge", "chrome", "google-chrome", "chromium", "chromium-browser"))]
    return next((k for k in kandidaten if k and os.path.isfile(k)), None)


def export_pdf(gruppierung="Thema"):
    """PDF: die HTML-Doku druckt Edge/Chrome ohne Fenster als A4-PDF."""
    browser = browser_pfad()
    if not browser:
        raise RuntimeError("Für PDF wird Microsoft Edge oder Google Chrome gebraucht (oder PDF_BROWSER setzen).")
    tmp = tempfile.mkdtemp(prefix="datenquellen_pdf_")
    try:
        html_pfad, pdf_pfad = os.path.join(tmp, "doku.html"), os.path.join(tmp, "doku.pdf")
        with open(html_pfad, "w", encoding="utf-8") as f:
            f.write(export_html(gruppierung))
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


EXPORTE = {  # Format: (Dateiendung, MIME-Typ, Funktion(gruppierung) -> str | bytes)
    "md": ("md", "text/markdown", export_markdown),
    "html": ("html", "text/html", export_html),
    "pdf": ("pdf", "application/pdf", export_pdf),
    "csv": ("csv", "text/csv", lambda gruppierung=None: export_csv()),
    "json": ("json", "application/json", lambda gruppierung=None: export_json()),
}


def dateiname(fmt):
    return f"datenquellen_{_stand()}.{EXPORTE[fmt][0]}"


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
