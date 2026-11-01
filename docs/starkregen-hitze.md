# Starkregen und Hitze: Early Prototype

Stand: 01.11.2026

## Ziel

Die ersten beiden Fragen aus der Werkzeug-Übersicht (siehe `baustellen-analyse.md`) sollen im Geo-Agenten beantwortbar werden:

| Frage | "Richtiges" Simulationswerkzeug | Prototyp (Stufe 1) |
|---|---|---|
| Was passiert bei Starkregen, wenn wir hier pflastern? | HEC-RAS 2D, LISFLOOD-FP, TELEMAC | Senken- und Fließweganalyse auf Höhenmodell + Versiegelung aus OSM |
| Wird es wärmer, wenn wir Bäume fällen oder Flächen versiegeln? | UMEP (SOLWEIG), PALM-4U, ENVI-met | Empirische Abschätzung aus Versiegelung und Baumkronen in der Nachbarschaft |

Es geht um eine **Machbarkeitsprüfung**: Kann ein LLM-Agent solche Fragen mit frei verfügbaren Daten in Sekunden grob beantworten, und wo liegen die Grenzen?

**Kurzfazit:** Technisch geht beides, schnell (0,2–3 s pro Rechnung) und offline. Die Grenzen liegen bei den **Daten**, nicht beim Code. Die Hitze-Abschätzung ist für eine Ersteinschätzung brauchbar. Die Starkregen-Abschätzung zeigt die Richtung (wohin fließt das Wasser, wie viel mehr), aber die **absoluten Überflutungsflächen sind mit dem groben Höhenmodell nicht belastbar**.

## Was umgesetzt ist

| Datei | Änderung |
|---|---|
| `climate_tools.py` (neu) | `starkregen(...)` und `hitze(...)`, Bodenbedeckungs-Raster aus OSM, Höhenmodell-Download, Senken/Fließwege |
| `local_osm.py` | `prepare_areas()` / `areas(bbox)`: Umrisse von Gebäuden, Flächen, Wegen aus der Hessen-Datei (`python local_osm.py areas`, einmalig ca. 3,5 min, 28 MB) |
| `geo_tools.py` | `_overpass(query, timeout, rounds)`: kürzere Timeouts möglich |
| `agent.py` | Werkzeuge `starkregen` und `hitze`, Arbeitsanleitung im Systemprompt |
| `app.py` | zwei Beispielfragen in der Seitenleiste |
| `app.py` + `ergebnisse_page.py` | Zwei Seiten: **Chat** und **Ergebnisse** (alle Karten und Dateien je Frage ansehen, Ebenen kombinieren, Attribute als Tabelle, Download, im Explorer/QGIS öffnen) |
| `geo_tools.py` / `agent.py` | Jede Frage bekommt einen eigenen Ordner `output/ergebnisse/<Datum_Uhrzeit>_<Frage>/` mit allen Dateien und `frage.md` (Frage, Antwort, Werkzeuge). Dateien aus früheren Fragen findet der Agent weiterhin über den Namen. Ältere Ausgaben wurden thematisch in solche Ordner einsortiert. |

### Gemeinsame Grundlage: Bodenbedeckung aus OSM

Für das Gebiet um die Maßnahme wird ein 5-m-Raster erzeugt. Jede Zelle bekommt eine Klasse:

| Klasse | Versiegelung | Abflussbeiwert (Starkregen) | Oberfläche Sommernachmittag |
|---|---|---|---|
| Gebäude | 100 % | 0,90 | ca. 45 °C |
| Asphalt (Straße) | 100 % | 0,90 | ca. 52 °C |
| Pflaster / Platz / Parkplatz | 90 % | 0,75 | ca. 45 °C |
| Gewerbe/Industrie (Rest) | 80 % | 0,75 | ca. 45 °C |
| Wohngebiet (Gärten/Höfe, Rest) | 45 % | 0,50 | ca. 38 °C |
| Grünfläche / Rasen | 0 % | 0,25 | ca. 33 °C |
| Acker / Wiese | 0 % | 0,30 | ca. 35 °C |
| Wald | 0 % | 0,10 | ca. 27 °C |
| Wasser | 0 % | 1,0 | ca. 25 °C |
| unbekannt | 35 % | 0,45 | ca. 38 °C |

Quelle: OSM-Umrisse (Gebäude, `landuse`, `leisure`, `natural`, Parkplätze), Straßen als Linien mit typischer Breite je Straßenklasse und `surface`-Tag. Baumkronen kommen zusätzlich aus Einzelbäumen (`natural=tree`, Krone 8 m bzw. `diameter_crown`), Baumreihen und Wald.

Alle Werte sind **typische Größenordnungen**, keine kalibrierten Werte. Sie stehen gesammelt oben in `climate_tools.py` (`COVER`) und lassen sich leicht anpassen.

Maßnahmen (Kreisfläche um den geocodierten Punkt, `radius_m`; Gebäude bleiben immer stehen):
`versiegeln` (pflastern), `asphaltieren`, `entsiegeln` (zu Grünfläche), `baeume_faellen`, `baeume_pflanzen` (ca. 60 % Kronendeckung).

> **Alle Zahlen unten sind Standardannahmen** und vom Agenten über den Parameter `annahmen` änderbar (seit 01.11.2026). Vollständige Liste: [annahmen.md](annahmen.md). Jede Antwort endet mit einer Annahmen-Tabelle.

### Starkregen: Methode

Vereinfachte Senken- und Fließweganalyse. So ähnlich arbeiten viele kommunale Starkregen-Hinweiskarten als erste Stufe, bevor hydrodynamisch gerechnet wird.

1. **Höhenmodell** (seit 01.11.2026, siehe Abschnitt "Update: DGM1 Hessen"):
   - In Hessen: **DGM1 Hessen** (Laserscan-Geländemodell der HVBG), auf 4 m gemittelt. Gebäude werden als Hindernisse +10 m eingebrannt. Wasserflächen unter 100 m² gelten als Pfütze.
   - Sonst / Dienst nicht erreichbar: AWS Terrain Tiles (EU-DEM/SRTM, ca. **25–30 m**) auf 10 m, mit Warnung im Ergebnis.
2. **Abfluss je Zelle:** Regen (Standard 50 mm in 1 h, grob ein 100-jährliches Ereignis in Südhessen) × Abflussbeiwert, minus pauschal 10 mm, die die Kanalisation von versiegelten Flächen aufnimmt.
3. **Senken füllen** (Priority-Flood) ergibt Fließrichtungen und Senken samt Fassungsvermögen.
4. **Wasser bergab weitergeben:** Senken füllen sich bis zum Rand, der Überschuss läuft weiter (oberliegende Senken zuerst). Wasser am Rand verlässt das Gebiet.
5. **Wasserstand je Senke** aus dem gespeicherten Volumen, von unten gefüllt.
6. Alles zweimal (vorher/nachher), dann vergleichen.

Ausgabe: zusätzlicher Oberflächenabfluss (m³), Weg des Wassers ab der Fläche, Senken mit mehr Wasser (Ort über nächste Straße, Tiefe vorher/nachher, läuft über ja/nein), Gebäude und sensible Einrichtungen mit ≥ 10 cm Wasser. Auf der Karte: Wassertiefe, Fließwege, "mehr Wasser", Fläche + Weg des Wassers, Gebäude (rot = neu betroffen).

### Hitze: Methode

Empirische Abschätzung für einen heißen Sommernachmittag:

- **Lufttemperatur:** Änderung = a · Δ(Versiegelung) − b · Δ(Baumkronen), jeweils als Anteil in der Nachbarschaft (Gauß-Gewichtung, σ = 50 m, also etwa 100 m Umkreis).
  - a = 2 K je 100 % Versiegelung (Spanne 1–3 K)
  - b = 3 K je 100 % Baumkronen (Spanne 2–5 K)
  - Größenordnungen aus der Literatur zu Stadtbäumen und Versiegelung, **nicht für Darmstadt kalibriert**.
- **Oberflächentemperatur** in der Fläche: Mittelwert der Klassenwerte, Baumschatten ca. 29 °C.
- **Gefühlte Temperatur:** fester Literaturhinweis (Baumschatten gefühlt ca. 10–15 °C kühler als Sonne auf Asphalt, PET), noch nicht gerechnet.

Ausgabe: entfallende Bäume, Kronenfläche und Versiegelung vorher/nachher, Anteile im 100-m-Umkreis, Oberflächentemperatur, maximale Änderung der Lufttemperatur mit Spanne, Fläche und Reichweite der Zone ab 0,1 K, Gebäude in der Zone, sensible Einrichtungen. Karte: Temperaturänderung in Klassen (rot wärmer, blau kühler), Fläche, entfallende Bäume, Einrichtungen.

## OpenStreetMap-API-Problem

Beim Test (01.11.2026) haben **alle drei öffentlichen Overpass-Server innerhalb von 10 s nicht geantwortet**, ein weiterer gab HTTP 504. Das bestätigt `osm-datenquellen.md`. Deshalb:

- Die neuen Werkzeuge nutzen **zuerst die lokalen Geofabrik-Daten**. Für Darmstadt + Umland (`LOCAL_OSM_BBOX`) braucht es keinen OSM-Server.
- Die bisherige Region-Datei kannte Gebäude/Flächen nur als **Mittelpunkte**. Für Versiegelung braucht es Umrisse, daher die neue Datei `data/osm/areas_*.pkl`.
- **Außerhalb der Region:** Overpass mit nur 12 s Timeout und einem Durchlauf (statt 25 s × 2). Schlimmster Fall ca. 50 s, dann klare Fehlermeldung. Getestet mit Frankfurt: Abbruch mit "Keine OSM-Flächendaten für dieses Gebiet (Overpass überlastet …)".
- Notlösung, falls `areas_*.pkl` fehlt und Overpass streikt: Gebäude als 12×12-m-Quadrate um den Mittelpunkt, Straßen aus dem lokalen Netz. Das liefert eine Warnung im Ergebnis.
- **Geocoding** läuft weiter über Nominatim (hat im Test funktioniert). Bei Ausfall greift die bestehende lokale Namenssuche.
- **Höhenmodell:** AWS-Kacheln, 12 s Timeout, danach aus dem Cache. Ohne Internet und ohne Cache gibt es keine Starkregen-Analyse. Die Hitze-Analyse braucht kein Höhenmodell und läuft komplett offline.

Zu den "simulierten Daten": Im Projekt gibt es keine simulierten Mess- oder Klimadaten. Vorhanden sind der lokale OSM-Auszug (offline) und die simulierten Durchgangsfahrten im Verkehrsmodell. Für die Tests wurde der lokale OSM-Auszug genutzt.

## Testergebnisse

Kurze Tests direkt auf Funktionsebene (ohne LLM), Darmstadt Herrngarten:

| Test | Dauer | Ergebnis |
|---|---|---|
| `local_osm.py areas` (einmalig) | 3,5 min | 112.123 Flächen, 48.450 Linien |
| `hitze`, Bäume fällen, r = 60 m | 1,6 s (erster Aufruf, inkl. Laden) | 17 Bäume / 825 m² Krone entfallen, Luft max. +0,11 K (0,07–0,18), Zone ab 0,1 K reicht ca. 46 m |
| `hitze`, versiegeln, r = 40 m | 0,2 s | 11 Bäume entfallen, Oberfläche 33,6 → 45,0 °C, Luft max. +0,56 K (0,30–0,86), Zone ab 0,1 K: 3,2 ha, bis ca. 100 m |
| `hitze`, Bäume pflanzen am Luisenplatz, r = 40 m | 0,3 s | Oberfläche 39,8 → 33,7 °C, Luft max. −0,49 K (−0,81 bis −0,32) |
| `starkregen`, versiegeln, r = 50 m | 2–3 s (inkl. Kacheln laden) | Abflussbeiwert 0,28 → 0,75, +121 m³ Oberflächenabfluss, fließt nach NW in eine Senke an der Schloßgartenstraße (Tiefe 100 → 101 cm) |
| Integrationstest über `agent.execute_tool` (geocode → starkregen/hitze → make_map) | je < 3 s | Karten unter `output/ergebnisse/2026-11-01_11-39-00_starkregen_tests/` und `..._hitze_tests/` |
| Fehlerfall Frankfurt (außerhalb Region, Overpass down) | ca. 10 s (Test mit 3-s-Timeout) | saubere Fehlermeldung |

**Test mit LLM** (Nemotron 3.5 Super über OpenRouter, ohne Streamlit, 01.11.2026):

| Frage | Dauer | Ablauf | Bewertung |
|---|---|---|---|
| *Was passiert bei Starkregen, wenn wir im Herrngarten Darmstadt 5000 m² pflastern?* | 36 s | geocode → starkregen (r = 40 m, richtig aus 5000 m² umgerechnet, `versiegeln`) → make_map (5 Ebenen, richtige Reihenfolge) | gut: +76 m³, Senke Schloßgartenstraße, keine neu betroffenen Gebäude, Hinweis auf grobe Abschätzung. **Schwäche:** nennt 4 Einrichtungen, die schon *vorher* 22–52 cm im Wasser stehen, ohne Einschränkung. Das ist sehr wahrscheinlich ein Artefakt des Höhenmodells und für Laien irreführend. |
| *Wird es wärmer, wenn wir im Herrngarten Darmstadt die Bäume fällen?* | 24 s | geocode → hitze (r = 50 m Standard, sagt das auch, `baeume_faellen`) → make_map (3 Ebenen) | gut: 17 Bäume, +0,13 K (0,08–0,21), Reichweite ca. 47 m, nennt OSM-Datenlücke. Der kleine Effekt liegt vor allem an den fehlenden Bäumen in OSM. |

Protokolle: `output/logs/session_2026-11-01_11-39-23.md` und `session_2026-11-01_11-40-07.md`, Karten im Ordner `output/ergebnisse/..._tests/`.

Mögliche Verbesserung: Bei Starkregen absolute Wassertiefen "vorher" nur mit Warnung ausgeben (oder ganz weglassen) und den Agenten anweisen, sich auf die *Änderung* zu konzentrieren.

## Erkenntnisse

### Was gut funktioniert

- **Schnell und offline:** Rasterisierung von ca. 10.000 OSM-Flächen und die Senkenanalyse auf 200×200 Zellen laufen in reinem Python/NumPy in Sekunden. Dafür braucht es weder QGIS noch zusätzliche Pakete wie rasterio oder scipy.
- **Vorher/Nachher-Vergleich** passt gut zur Fragestellung "Was passiert, wenn …?". Viele Fehler (grobes Höhenmodell, pauschale Beiwerte) wirken vorher und nachher gleich und heben sich im Unterschied teilweise auf.
- Die Klassifizierung aus OSM ist in Darmstadt plausibel, z.B. Herrngarten: 92 % Grünfläche, Rest Wege/Gebäude.
- Die Werkzeuge liefern dieselbe Art von Ergebnis wie die Baustellen-Werkzeuge (Zahlen + GeoJSON mit Stil/Popup). Der Agent kann sie genauso nutzen.

### Problematisch

1. **Höhenmodell zu grob für Starkregen (größtes Problem).** 25–30 m Auflösung und eher ein Oberflächenmodell: Bordsteine, Straßenprofile, Unterführungen, Mauern und Gebäude als Hindernisse fehlen. Folge: Die Senken sind teils Artefakte. Im Test standen im 2×2-km-Gebiet um den Herrngarten 15,7 ha unter ≥ 10 cm Wasser und 219 Gebäude "nass", vermutlich deutlich zu viel. Belastbar ist eher die **Richtung** (wohin fließt das Wasser) und die **Menge** (zusätzliche m³). Die Überflutungsfläche ist es nicht.
2. **Bäume in OSM unvollständig.** Im Herrngarten liegt die Kronenfläche nach OSM bei nur ca. 10 %, real deutlich mehr. Fehlende Bäume heißt: Der Effekt von "Bäume fällen" wird **unterschätzt**. Parks ohne Einzelbäume gelten als Rasen.
3. **Hitze-Koeffizienten nicht kalibriert.** Die Spanne (Faktor ca. 2–3) zeigt die Unsicherheit. Keine Nacht (dort wirkt Versiegelung als Wärmespeicher stärker), kein Wind, keine Gebäudeschatten.
4. **Kanalisation pauschal** (10 mm). Real hängt es vom Kanalnetz ab, und darüber hat die Stadt Daten, OSM nicht.
5. **Starkregen ohne Zeit/Fließgeschwindigkeit:** keine Aussage, wann und wie schnell Wasser kommt. Das können nur 2D-Modelle.
6. **Multipolygone:** Ob große Flächen aus OSM-Relationen (z.B. große Parks, Wälder) vollständig im Flächen-Auszug sind, ist nicht geprüft.

### Bewertung der Machbarkeit

| | Ersteinschätzung per Agent | Belastbare Aussage |
|---|---|---|
| Hitze | **machbar**, mit Spanne und Hinweis auf Datenlücken | braucht Baumkataster + UMEP/SOLWEIG (Stufe 2) |
| Starkregen | **eingeschränkt machbar**: Richtung und Mehrmenge ja, Überflutungsflächen nein | braucht DGM1 + 2D-Modell (Stufe 2) oder die vorhandene Starkregen-Gefahrenkarte der Stadt |

## Update: DGM1 Hessen (01.11.2026, Branch `aaron-proto-dgm1`)

Erster Schritt Richtung "richtige Simulation": das genaue Geländemodell statt des groben Satellitenmodells.

**Datenquelle:** INSPIRE-Download-Dienst (WCS 2.0.1) der HVBG, `https://inspire-hessen.de/raster/dgm1/ows`

- Ganz Hessen, Laserscan, 1 m (`he_dgm1`) und gröbere Stufen 2/4/8/16/32 m (`he_dgm1_2` …), Datenstand 2025 H2
- **Lizenz: Datenlizenz Deutschland – Zero – 2.0**, also frei nutzbar, keine Gebühren, keine Namensnennung nötig
- Kein Key, GeoTIFF direkt per URL. 500 × 500 m in 1 m sind ca. 1 MB in 0,4 s, 2 × 2 km in 2 m ca. 4 MB in 1–2 s
- Cache in `output/cache/dgm1/`, danach offline

**Umsetzung** (`climate_tools._dgm1`):

- 2-m-Stufe laden, bilinear auf ein 4-m-Rechenraster.
- Gebäudezellen (≥ 50 % Gebäude nach OSM) +10 m: Wasser fließt um Gebäude herum und staut sich davor.
- Wasserflächen unter 100 m² (`MIN_POND_M2`) ausblenden. Mit dem feinen Gelände entstehen sonst über 1.000 Mini-Pfützen an Hauswänden, die real über Gullys abfließen.
- Rückfall auf AWS-Kacheln mit Warnung, falls außerhalb Hessens oder der Dienst nicht antwortet (25 s Timeout).

**Vergleich** am Herrngarten (versiegeln, r = 40 m; Karten in `output/ergebnisse/2026-11-01_13-03-27_vergleich_dgm1_herrngarten/`):

| | Alt (AWS 30 m, 10-m-Raster) | DGM1 + Gebäude + Pfützenfilter (4 m) |
|---|---|---|
| Fläche ab 10 cm / ab 30 cm (2 × 2 km) | 16,4 / 9,3 ha | **11,4 / 4,2 ha** |
| große Wasserflächen > 5.000 m² | 12 (14 ha) | 2 (ca. 1 ha) |
| Gebäude mit Wasser ab 10 cm | 224 | 990 |
| Wasser von der Fläche fließt in Senke | Schloßgartenstraße (134 m) | Frankfurter Straße (55 m) |
| Laufzeit | 2,5 s | 3,8 s |

**Bewertung:**

- Die großen Artefakt-Seen des groben Modells sind weg. Die Flächen ab 30 cm halbieren sich, und die Fließwege folgen jetzt Straßen statt geglätteten Hängen.
- Dafür zeigt das feine Gelände viele kleinere echte Mulden, z.B. eine ca. 3,5 m tiefe Senke an der Heinrich-Hoffmann-Schule. Deshalb sind deutlich mehr Gebäude "nass". Ob 990 realistisch ist, lässt sich nur mit einer Referenz klären (Starkregen-Gefahrenkarte der Stadt, BKG-Hinweiskarte).
- Weiterhin ohne Kanalnetz (pauschal 10 mm), ohne Zeit/Geschwindigkeit. Abgeschlossene Innenhöfe können zu nass erscheinen.
- Feiner als 4 m ist mit der reinen Python-Senkenrechnung zu langsam (1 m auf 2 × 2 km wären 4 Mio. Zellen). Für 1–2 m braucht es ein kompiliertes Werkzeug (z.B. LISFLOOD-FP, siehe unten).

**Nächster Schritt:** Pilot mit LISFLOOD-FP auf demselben DGM1-Ausschnitt und Abgleich mit einer vorhandenen Starkregen-Gefahrenkarte.

## Nächste Schritte (Stufe 2)

Bessere Daten (größter Hebel, wenig Code):

| Daten | Wofür | Hinweis |
|---|---|---|
| **DGM1 Hessen** (HVBG, 1-m-Geländemodell) | Starkregen | **erledigt** (siehe Update oben): frei per WCS, Datenlizenz Zero |
| **Baumkataster Darmstadt** | Hitze | Bei der Stadt nachfragen (Open-Data-Portal?), alternativ Copernicus *Street Tree Layer* / *Tree Cover Density* |
| **Copernicus HRL Imperviousness** (10 m) | beide | Versiegelungsgrad als Raster, ergänzt/prüft die OSM-Klassifizierung |
| **Starkregen-Gefahrenkarte** (Stadt Darmstadt / HLNUG) | Starkregen | Zur Plausibilitätsprüfung unserer Senken, ggf. als Hintergrund-Layer |
| Landsat-Oberflächentemperatur | Hitze | Zur Kalibrierung der Klassenwerte (frei, 30 m) |

Bessere Modelle (mehr Aufwand):

- **Hitze: UMEP/SOLWEIG** als QGIS-Plugin per `qgis_process` aufrufen, wie die anderen QGIS-Algorithmen. UMEP ist auf dem Entwicklungsrechner **noch nicht installiert** (kein QGIS-Plugin-Ordner gefunden). Benötigt: Gebäudehöhen-Oberflächenmodell (aus OSM-Geschosszahlen machbar, ca. 45 % der Gebäude im Zentrum haben `building:levels`/`height`), Vegetationsmodell, Wetterdaten (DWD).
- **Starkregen: LISFLOOD-FP oder HEC-RAS 2D** mit DGM1. LISFLOOD-FP ist schlanker und per Kommandozeile automatisierbar. HEC-RAS ist kostenlos, aber Windows-GUI-lastig.

Kleinere Verbesserungen am Prototyp:

- Maßnahme als echte Fläche statt Kreis, z.B. "der Parkplatz X" als OSM-Polygon.
- Kanalisationskapazität und Regenmenge als Agent-Parameter (KOSTRA-DWD-Werte für Darmstadt).
- Gebäude als Hindernisse ins Höhenmodell einbrennen (+3 m), sobald ein genaueres DGM da ist.

## Testfragen

- *Was passiert bei Starkregen, wenn wir im Herrngarten Darmstadt 5000 m² pflastern?*
- *Wird es wärmer, wenn wir im Herrngarten Darmstadt die Bäume fällen?*
- *Was bringt es fürs Klima, wenn wir den Parkplatz am Karolinenplatz Darmstadt entsiegeln und Bäume pflanzen?* (beide Werkzeuge)
- *Wir wollen am Luisenplatz Darmstadt 30 Bäume pflanzen. Wie stark kühlt das?*
