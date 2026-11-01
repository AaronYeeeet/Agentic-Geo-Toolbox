# Baustellen-Analyse: Lärm und Verkehr

Stand: 28.10.2026

## Ziel

Mitarbeitende einer Kommune sollen in normaler Sprache fragen können, z.B.:

> *"Was bedeutet eine Baustelle an der Rheinstraße / Ecke Neckarstraße für Lärm und Verkehr?"*

Der Geo-Agent beantwortet das mit Zahlen und einer Karte (OpenStreetMap-Hintergrund): Welche Straßen bekommen mehr Verkehr, wie lang werden die Umwege, wie laut wird es wo, und welche Gebäude, Schulen, Kitas und Krankenhäuser sind betroffen?

## Werkzeuge für "Was passiert, wenn ...?"-Fragen (Überblick)

| Frage | Simulationswerkzeug | Open Source? | Verbindung zu QGIS |
|---|---|---|---|
| Starkregen / Versiegelung | HEC-RAS 2D, LISFLOOD-FP, TELEMAC; kommerziell InfoWorks | HEC-RAS kostenlos, Rest offen | Geländemodell + Versiegelung rein, Überflutungskarte raus |
| Hitze (Bäume fällen, versiegeln) | UMEP (QGIS-Plugin), PALM-4U, ENVI-met | UMEP, PALM-4U ja; ENVI-met kommerziell | UMEP läuft direkt in QGIS |
| Verkehr (neue Straße, Sperrung) | SUMO (DLR), MATSim, PTV Visum/Vissim | SUMO, MATSim ja | Straßennetz aus OSM, Ergebnisse zurück ins GIS |
| Lärm | NoiseModelling, QGIS-Lärmplugins | ja | direkt mit GIS-Daten |
| Schatten durch Neubau | UMEP, Ladybug, Cesium | größtenteils ja | 3D-Gebäude / Höhenmodell nötig |
| Wind zwischen Hochhäusern | OpenFOAM (CFD) | ja | sehr aufwendig, Spezialistenarbeit |

Dieses Dokument behandelt **Verkehr und Lärm bei Baustellen**. Starkregen und Hitze: siehe `starkregen-hitze.md`.

## Zwei Stufen

### Stufe 1: Schnelle Abschätzung (wird umgesetzt)

Läuft in Sekunden bis wenigen Minuten, kostenlos und nur mit OSM-Daten.

| Schritt | Was passiert | Umsetzung |
|---|---|---|
| 1. Ort finden | Adresse / Kreuzung -> Koordinaten | Nominatim (OSM-Adresssuche) |
| 2. Verkehr | Straßennetz um die Baustelle laden, gesperrte Abschnitte entfernen, viele Beispielfahrten durch das Gebiet vorher und nachher berechnen | OSMnx + NetworkX |
| 3. Baulärm | Baustelle als Lärmquelle (typischer Schallleistungspegel), Lärmringe für 75/70/65/60/55 dB(A), betroffene Gebäude und sensible Einrichtungen zählen | einfache Schallausbreitung + OSM-Daten |
| 4. Verkehrslärm | Pegeländerung auf Umleitungsstraßen aus der Verkehrsänderung: doppelter Verkehr ≈ +3 dB | 10·log10(nachher/vorher) |
| 5. Karte | Sperrung (schwarz), Straßen mit mehr (rot) / weniger (grün) Verkehr, Lärmringe, Schulen/Kitas/Kliniken | Leaflet + OSM, in Streamlit angezeigt |

Neue Werkzeuge für den Agenten:

- `geocode(ort)`: Koordinaten zu Adresse oder Kreuzung
- `traffic_impact(lat, lon, ...)`: Verkehrsverlagerung, Umwege, Verkehrslärm-Änderung
- `construction_noise(lat, lon, lautstaerke)`: Baulärm-Ringe, betroffene Gebäude und Einrichtungen

> **Alle Zahlen unten sind Standardannahmen** und vom Agenten über den Parameter `annahmen` änderbar (seit 01.11.2026). Vollständige Liste: [annahmen.md](annahmen.md). Jede Antwort endet mit einer Annahmen-Tabelle.

#### Methode Verkehr

- Straßennetz für Autos im Umkreis (Standard 1,5 km) aus OSM.
- Gesperrt werden alle Straßenabschnitte bis ca. 30 m um die Baustelle (einstellbar).
- **Durchgangsverkehr-Modell:** Viele zufällige Fahrten zwischen Punkten am Rand des Gebiets, jeweils auf dem kürzesten Weg, einmal vorher und einmal nachher.
- Pro Straßenabschnitt wird gezählt, wie viele Fahrten ihn nutzen. Die Differenz zeigt, wohin sich Verkehr verlagert.
- Umweg = Weglänge nachher minus vorher für die betroffenen Fahrten.

#### Methode Baulärm

- Punktquelle über Boden: L(r) = Lw − 20·log10(r) − 8 dB
- Lw nach Tätigkeit (typische Größenordnungen): **normal** 105 dB(A) (Bagger, Lkw), **laut** 112 dB(A) (Abbruch, Stemmen), **sehr laut** 120 dB(A) (Rammen, Spundwände).
- Zum Vergleich die Immissionsrichtwerte der AVV Baulärm (tags): Krankenhäuser 45, reine Wohngebiete 50, allgemeine Wohngebiete 55, Mischgebiete 60 dB(A).

#### Grenzen von Stufe 1 (wichtig)

Das Ergebnis ist eine **grobe Abschätzung**, keine Lärmberechnung nach Vorschrift und keine Verkehrsprognose:

- Keine echten Verkehrsmengen: Das Modell zeigt **relative** Verlagerung, keine Fahrzeuge pro Tag.
- Alle fahren den kürzesten Weg. Ampeln, Stau und Tempo werden nicht berücksichtigt.
- Lärm ohne Abschirmung durch Gebäude, ohne Reflexionen und ohne Wetter. In engen Straßen ist es real teils lauter, hinter Gebäuden leiser.
- Teilsperrungen (eine Spur offen) werden wie Vollsperrungen behandelt.

Für eine erste Einschätzung ("wen betrifft das ungefähr, welche Straßen sollte man im Blick haben?") reicht das, für Bescheide oder Gutachten nicht.

### Stufe 2: Echte Simulation (später)

| Thema | Werkzeug | Was es besser kann |
|---|---|---|
| Verkehr | **SUMO** (DLR) | Fahrzeugsimulation mit Ampeln, Spuren, Stau; Teilsperrungen; Netz aus OSM per `netconvert` |
| Lärm | **NoiseModelling** | Lärmberechnung nach EU-Norm CNOSSOS-EU mit Gebäudeabschirmung und Reflexionen |

Beide sind Open Source und könnten vom Agenten wie heute QGIS als Werkzeug aufgerufen werden. Dafür werden Annahmen bzw. Daten zum Verkehrsaufkommen gebraucht, z.B. Verkehrszählungen der Stadt Darmstadt.

## Testfragen

- *Was bedeutet eine Baustelle an der Kreuzung Rheinstraße / Neckarstraße in Darmstadt für Verkehr und Lärm?*
- *Wir planen Abbrucharbeiten am Karolinenplatz Darmstadt. Welche Schulen und Kitas sind lärmbetroffen?*
- *Wohin verlagert sich der Verkehr, wenn die Heinrichstraße am Ostbahnhof gesperrt wird?*
