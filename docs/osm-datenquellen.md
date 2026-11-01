# OpenStreetMap-Daten für den Geo-Agenten

Stand: 28.10.2026

## Problem

Der Agent holt OSM-Daten über die **Overpass API** (`fetch_osm` in `geo_tools.py`). Die öffentlichen Overpass-Server sind oft überlastet und antworten mit 502/504, brechen den Verbindungsaufbau ab oder antworten gar nicht.

Gründe:
- Die Server werden von Freiwilligen betrieben, ohne Verfügbarkeitsgarantie.
- Sehr viele Apps, Bots und Forschungsprojekte fragen dort kostenlos ab.
- Pro IP sind nur ca. 2 Abfragen gleichzeitig erlaubt.

OpenStreetMap selbst ist dabei nicht kaputt, nur der kostenlose Abfragedienst. Für einen Prototyp ist das normal, für eine Live-Demo ein Risiko.

## Bereits umgesetzt (in `geo_tools.py`)

| Maßnahme | Wirkung |
|---|---|
| 4 Overpass-Server als Ausweichlösung, 2 Durchläufe | Ein ausgefallener Server legt nichts lahm |
| Funktionierender Server wird beim nächsten Mal zuerst gefragt | Weniger Fehlversuche |
| Timeout 25 s pro Server (vorher 90 s) | Schlimmster Fall ca. 3,5 statt 12 Minuten |
| Zwischenspeicher in `output/cache/`, 7 Tage gültig | Gleiche Abfrage -> Ergebnis in Millisekunden, ohne Server |

**Lokale Geofabrik-Daten** (`local_osm.py`): Region-Datei mit Mittelpunkten und Straßennetz, zusätzlich seit 01.11.2026 eine Datei mit Umrissen (Gebäude, Flächen, Wege) für Starkregen/Hitze: `python local_osm.py areas` (einmalig ca. 3,5 min).

**Tipp für Demos:** Die Demo-Frage vorher einmal stellen, damit die Daten im Cache liegen. Das hilft aber nur, wenn das Modell genau dasselbe Gebiet abfragt.

## Optionen für einen zuverlässigeren Zugriff

### Bezahlt

| Anbieter | Was | Passt für uns? |
|---|---|---|
| Geoapify | API mit OSM-Daten, z.B. Places-Abfrage nach Kategorie (Ladesäulen, Parkplätze ...). Kostenlose Stufe + bezahlte Pakete | Am ehesten: "Overpass mit Garantie", aber nur vordefinierte Kategorien |
| MapTiler / Mapbox / Stadia Maps | Kartenkacheln, Geocoding auf OSM-Basis | Eher nicht, keine freien Objekt-Abfragen |
| Geofabrik (kommerziell) | Individuelle Datenauszüge, Support | Nur bei Bedarf an Sonderauszügen |

Einen offiziellen bezahlten Zugang zu Overpass selbst gibt es nicht. Preise und Konditionen beim jeweiligen Anbieter prüfen.

### Kostenlos

1. **Regionaler Download von Geofabrik**: https://download.geofabrik.de
   - Hessen: ca. 300 MB, Deutschland: ca. 4–5 GB (`.osm.pbf`), täglich aktualisiert
   - QGIS/GDAL können die Datei direkt lesen
2. **Gefilterter Auszug als GeoPackage**
   - Relevante Kategorien einmal aus der `.pbf` herausziehen und als GeoPackage mit räumlichem Index speichern
   - Klein, schnell, offline, kein Server nötig
   - Nachteil: nur Kategorien, die vorher ausgewählt wurden
3. **Eigener Overpass-Server (Docker)**
   - Gleiche Abfragesprache wie die öffentlichen Server, aber nur für uns
   - Im Agenten muss nur die eigene Adresse vorne in `OVERPASS_SERVERS` stehen
4. **ohsome API** (HeiGIT, Uni Heidelberg): https://api.ohsome.org
   - Kostenlos, für Forschung gedacht, inkl. OSM-Historie (z.B. "wie viele Ladesäulen gab es 2020 vs. heute")

Zusätzlich beim Betreuer (Fraunhofer IGD) nachfragen, ob intern schon eine OSM- oder Overpass-Instanz existiert.

## Eigener Overpass-Server: Hessen vs. Deutschland

Grobe Schätzwerte, nicht gemessen:

| | Hessen | Deutschland |
|---|---|---|
| Download (`.osm.pbf`) | ca. 300 MB | ca. 4–5 GB |
| Datenbank nach Import | wenige GB | ca. 20–40 GB |
| Import-Dauer (einmalig) | Minuten bis ca. 1 h | mehrere Stunden (über Nacht) |
| Abfragen | meist < 1 s | meist < 1 s |

Vorhandene Hardware (Entwicklungsrechner): 286 GB frei, 16 GB RAM, 16 Kerne, Docker installiert. Beides ist machbar.

## Empfehlung

- **Kurzfristig / Uni-Demo:** Cache (ist umgesetzt) und vorher einmal "aufwärmen".
- **Wenn Overpass weiter Probleme macht:** eigener Overpass-Server mit **Hessen** zum Ausprobieren, später bei Bedarf auf **Deutschland** umstellen. Das passt am besten zur Aufgabe: Das LLM soll Datenquellen frei abfragen können, und dafür braucht es die volle Overpass-Abfragesprache.
- **GeoPackage-Auszug** als Alternative, wenn nur wenige feste Kategorien gebraucht werden.

## Anleitung: Overpass-Server mit Docker (Hessen)

> Noch nicht ausprobiert. Die Befehle folgen der Doku des Docker-Images `wiktorn/overpass-api` (https://hub.docker.com/r/wiktorn/overpass-api). Vor dem Start dort gegenprüfen.

```powershell
docker run -d --name overpass-hessen `
  -e OVERPASS_META=no `
  -e OVERPASS_MODE=init `
  -e OVERPASS_PLANET_URL=https://download.geofabrik.de/europe/germany/hessen-latest.osm.pbf `
  -e OVERPASS_DIFF_URL=https://download.geofabrik.de/europe/germany/hessen-updates/ `
  -e OVERPASS_UPDATE_SLEEP=3600 `
  -e OVERPASS_RULES_LOAD=10 `
  -v overpass-hessen-db:/db `
  -p 12345:80 `
  wiktorn/overpass-api
```

- Den Import-Fortschritt zeigt `docker logs -f overpass-hessen`.
- Danach ist der Server unter `http://localhost:12345/api/interpreter` erreichbar.
- Für Deutschland `hessen` in beiden URLs durch `germany` ersetzen, einen eigenen Container- und Volume-Namen nehmen und deutlich mehr Zeit einplanen.

Einbinden in `geo_tools.py`, die eigene Adresse an erster Stelle:

```python
OVERPASS_SERVERS = [
    "http://localhost:12345/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    # ... restliche öffentliche Server als Ausweichlösung
]
```

## Anleitung: GeoPackage-Auszug (Alternative ohne Server)

> Ebenfalls noch nicht ausprobiert. `ogr2ogr` wird mit QGIS mitgeliefert (`C:\Program Files\QGIS 3.44.15\bin\`), am einfachsten in der **OSGeo4W Shell** ausführen.

```bat
:: Punkte (z.B. Ladesäulen als Knoten) und Flächen (z.B. Parkplätze als Polygone) übernehmen
ogr2ogr -f GPKG hessen_osm.gpkg hessen-latest.osm.pbf points
ogr2ogr -f GPKG -update hessen_osm.gpkg hessen-latest.osm.pbf multipolygons
```

- Viele Tags (z.B. `amenity` bei Punkten) landen im Feld `other_tags`. Gefiltert wird per SQL bzw. mit QGIS-Algorithmen wie `native:extractbyexpression`.
- Für ganz Deutschland vorher mit `osmium tags-filter` auf die benötigten Kategorien reduzieren, sonst wird die Datei sehr groß.
