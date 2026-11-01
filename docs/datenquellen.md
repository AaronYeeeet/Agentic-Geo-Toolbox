# Freie Datenquellen und Modus „Nur Datenquellen“

Stand 01.11.2026, Branch `aaron-proto-datenquellen`. Code: [datenquellen.py](../datenquellen.py), Seite [datenquellen_page.py](../datenquellen_page.py).

## Kurzfassung

- **59 freie Datenquellen ohne API-Key** sind eingebunden: Wetter und Klima, Starkregen, Hitze, Luft, Wasser, Lärm, Schutzgebiete, Boden, Bevölkerung, Energie, Unfälle, ÖPNV, Satellitenbilder, Wissen sowie Open-Data-Kataloge und beliebige WFS-, WMS- und ArcGIS-Dienste. Dazu kommen wie bisher OpenStreetMap (`fetch_osm`) und QGIS.
- Der Agent ruft alle Quellen über **ein** Werkzeug auf: `datenquelle_abfragen` (Details über `datenquellen_katalog`). Kleine Modelle müssen also nicht zwischen 60 Werkzeugen wählen.
- **Selbsttest am Luisenplatz Darmstadt: 58 von 59 Quellen funktionieren**, fast alle in unter 2 s beim ersten Aufruf. Ausgefallen ist der BfN-WFS (der Dienst meldete „under maintenance“).
- **Schalter in der Seitenleiste „🧩 Eigene Analyse-Skills“:**
  - **an** = wie bisher (hitze, starkregen, ladesaeulen, traffic_impact, construction_noise) plus alle Datenquellen.
  - **aus** = Modus **„Nur Datenquellen“**: Der Agent bekommt die selbst gebauten Werkzeuge gar nicht mehr angeboten, sondern nur Daten, OSM und QGIS-Algorithmen.
  - Der Modus wird je Chat gespeichert. Beim Umschalten bleibt der Verlauf erhalten.
- **Neue Seite „Datenquellen“** mit drei Tabs: Katalog, jede Quelle ohne LLM ausprobieren (mit Karte) und Selbsttest aller Quellen.
- **Jede Karte** hat jetzt einen umschaltbaren Hintergrund: OpenStreetMap, basemap.de, Luftbild Hessen (20 cm) und Liegenschaftskarte Hessen.
- Unter jeder Antwort steht eine Tabelle **„Genutzte Datenquellen“** mit Anbieter, Stand, Lizenz und Link. Sie wird direkt aus den Ergebnissen erzeugt, nicht vom Modell abgeschrieben.

## Wie die Quellen angebunden sind

Gemäß dem Lab-Ziel ruft der Agent bestehende Dienste und Werkzeuge auf, statt eigene Modelle zu rechnen. Jede Quelle ist nur ein dünner Adapter: Sie fragt ab, schneidet auf den Umkreis zu und fasst zusammen.

| Technik | Beispiele | Werkzeug |
|---|---|---|
| JSON-APIs | Open-Meteo, Bright Sky (DWD), UBA, PEGELONLINE, Transitous, Valhalla, GBIF, Wikipedia/Wikidata, MaStR, SMARD, Autobahn GmbH | `requests` |
| ArcGIS-REST (query/identify) | HLNUG: Starkregen-Hinweiskarte, Hitzeviewer, Lärmkartierung, Hochwasser, Schutzgebiete, Boden, Geologie, Radon | `requests` → GeoJSON |
| WFS | BfN-Schutzgebiete, beliebige WFS (`wfs_abfrage`) | **ogr2ogr** (GDAL aus QGIS) |
| Cloud-Raster (COG) | ESA WorldCover, Sentinel-2 (NDVI), Landsat (Oberflächentemperatur) | **gdalwarp / gdal_translate** mit `/vsicurl/` |
| NetCDF | DWD UHI-MAP (städtische Wärmeinsel) | **gdallocationinfo** |
| ESRI-ASCII-Raster | KOSTRA-DWD-2020, DWD-Jahresraster 1 km | numpy |
| WMS | DWD-Klimakarten (GetFeatureInfo), Luftbild/ALKIS Hessen (GetMap), beliebige WMS (`wms_abfrage`) | `requests` |
| Lokale Dateien | Zensus 2022, Ladesäulenregister, Unfallatlas (einmal geladen, dann lokal) | numpy |

Jedes Ergebnis enthält:

- **`quelle`**: Name, Anbieter, Lizenz, Stand und Link.
- **`zusammenfassung`**: kompakt, für das LLM gekürzt.
- **`files`**: GeoJSON in EPSG:4326 im Ergebnisordner der Frage. Die Dateien gehen direkt an `make_map` oder als Eingabe an QGIS-Algorithmen. Rasterdaten werden als eingefärbte Kacheln gespeichert, mit höchstens 60 × 60 Zellen.

Zwischenspeicher liegen in `output/cache/datenquellen/`, je nach Quelle 3 Minuten bis 1 Jahr. Zum Download-Umfang:

- Der **Unfallatlas** lädt beim ersten Aufruf etwa 13 MB je Jahr und speichert es kompakt in `data/unfallatlas/`.
- **KOSTRA**, **DWD-Raster** und **UHI-Dateien** sind je unter 1 MB.

Testen ohne Oberfläche:

```bash
.venv\Scripts\python datenquellen.py test
```

```bash
.venv\Scripts\python datenquellen.py test hlnug_laerm unfallatlas
```

## Alle Quellen

Die Spalte „Test“ zeigt die Zeit beim ersten Aufruf ohne Cache am Luisenplatz (49.8728, 8.6512) mit Standard-Umkreis. Die Testparameter stehen in `TEST_PARAMETER` in datenquellen.py.

### Wetter & Klima

| ID | Was | Anbieter | Lizenz | Test |
|---|---|---|---|---|
| `wetter_aktuell` | Messwerte der nächsten DWD-Station: Temperatur, Niederschlag, Wind, Feuchte, Bewölkung. | Deutscher Wetterdienst über Bright Sky | DWD Open Data (CC BY 4.0) | OK, 0.5 s |
| `wetter_vorhersage` | Tageswerte der nächsten Tage: Höchst-/Tiefstwert, Niederschlag, Regenwahrscheinlichkeit, Böen, UV, Sonne. Parameter: `tage` | Open-Meteo | CC BY 4.0 | OK, 0.5 s |
| `wetter_historisch` | Tageswerte seit 1940 ausgewertet je Jahr: heiße Tage, Sommertage, Tropennächte, Frosttage, Niederschlag, Extreme. Parameter: `von`, `bis` | Open-Meteo / Copernicus ERA5 | CC BY 4.0 | OK, 0.8 s |
| `klima_projektion` | Vergleich 1991-2020 mit der Zukunft (bis 2050) aus mehreren Klimamodellen: heiße Tage, Tropennächte, Starkregentage. Parameter: `zukunft`, `modelle` | Open-Meteo / CMIP6 HighResMIP | CC BY 4.0 | OK, 0.8 s |
| `unwetterwarnungen` | Aktuelle DWD-Warnungen für die Gemeinde (Gewitter, Starkregen, Hitze, Sturm, Glätte ...). | Deutscher Wetterdienst über Bright Sky | DWD Open Data (CC BY 4.0) | OK, 0.5 s |
| `nina_warnungen` | Aktuelle Warnungen für den Landkreis/die kreisfreie Stadt: Katastrophenschutz, Polizei, Hochwasser, Wetter. | Bundesamt für Bevölkerungsschutz (NINA) | Datenlizenz Deutschland | OK, 1.2 s |
| `regenradar` | Niederschlag der letzten 2 Stunden und Kurzfrist-Vorhersage aus dem Radar (1 km), am Punkt und im Umkreis. | Deutscher Wetterdienst über Bright Sky | DWD Open Data (CC BY 4.0) | OK, 0.6 s |
| `kostra_starkregen` | Amtliche Regenmengen (mm) je Dauer (5 min bis 7 Tage) und Wiederkehrzeit (1 bis 100 Jahre), Raster 5 km. Parameter: `dauern_min` | Deutscher Wetterdienst | DWD Open Data (CC BY 4.0) | OK, 1.7 s |
| `dwd_klimaraster` | Gemessene Jahreswerte am Ort (1-km-Raster aus Stationen): heiße Tage, Sommertage, Frost, Starkregentage, Niederschlag, Temperatur, Sonne; mit Mittel 1961-1990 und 1991-2020 und Trend. Parameter: `groessen`, `von_jahr`, `bis_jahr` | Deutscher Wetterdienst (CDC) | DWD Open Data (CC BY 4.0) | OK, 9.8 s |
| `stadtklima_waermeinsel` | Wie viel wärmer es am Ort durch die Bebauung ist als im Umland (Kelvin) und zusätzliche Tropennächte, je Jahr, ca. 1 km. Parameter: `jahre` | Deutscher Wetterdienst (Projekt UHI-MAP) | DWD Open Data (CC BY 4.0) | OK, 12.0 s |
| `dwd_klimakarten` | Langjährige Mittel am Ort: Sommer-/Frost-/Schneetage, Sonnenscheindauer, Globalstrahlung, Wind in 10 und 80 m. | Deutscher Wetterdienst | DWD Open Data (CC BY 4.0) | OK, 2.3 s |
| `hlnug_hitze` | Maximale Landoberflächentemperatur (Satellit), Hot/Cold Spots, Hitzebelastungs-Index und Hitzebelastung im Sommer. | HLNUG | Datenlizenz Deutschland – Namensnennung 2.0 | OK, 6.8 s |

### Luft & Gesundheit

| ID | Was | Anbieter | Lizenz | Test |
|---|---|---|---|---|
| `luft_messstationen` | Nächste Messstationen der Länder mit aktuellen Stundenwerten für NO2, Feinstaub PM10/PM2.5 und Ozon. | Umweltbundesamt | Datenlizenz Deutschland – Namensnennung 2.0 | OK, 7.7 s |
| `luft_modell` | Modellwerte am Ort: Europäischer Luftqualitätsindex, PM10, PM2.5, NO2, Ozon, Pollen (Erle, Birke, Gräser ...). | Open-Meteo / Copernicus CAMS | CC BY 4.0 | OK, 0.7 s |
| `buergersensoren_luft` | Feinstaub- und Temperatursensoren von Bürger:innen im Umkreis (5-Minuten-Werte, nicht kalibriert). | sensor.community (Luftdaten.info) | ODbL 1.0 | OK, 0.9 s |
| `opensensemap` | Offene Umweltsensoren (Temperatur, Feuchte, Feinstaub, Lärm ...) mit letztem Messwert, nur aktive (< 48 h). | openSenseMap (Uni Münster / re:edu) | PDDL 1.0 | OK, 0.4 s |
| `pollenflug` | Pollenbelastung heute/morgen/übermorgen je Pollenart für eine DWD-Teilregion. Parameter: `region` | Deutscher Wetterdienst | DWD Open Data (CC BY 4.0) | OK, 0.8 s |
| `uv_index` | UV-Index heute, morgen, übermorgen für die nächstgelegene DWD-Vorhersagestadt. | Deutscher Wetterdienst | DWD Open Data (CC BY 4.0) | OK, 0.8 s |

### Wasser & Hochwasser

| ID | Was | Anbieter | Lizenz | Test |
|---|---|---|---|---|
| `pegel` | Pegel im Umkreis mit aktuellem Wasserstand (cm), Abfluss und Einordnung (niedrig/normal/hoch). | Wasserstraßen- und Schifffahrtsverwaltung des Bundes | Datenlizenz Deutschland – Zero 2.0 | OK, 1.0 s |
| `abfluss_vorhersage` | Abfluss des nächsten größeren Flusses (m³/s): letzte 7 Tage und 2 Wochen Vorhersage, mit langjährigem Mittel. | Open-Meteo / Copernicus GloFAS | CC BY 4.0 | OK, 1.2 s |
| `hlnug_hochwasser` | Überflutungsflächen für häufiges, seltenes und extremes Hochwasser und festgesetzte Überschwemmungsgebiete. | Hessisches Landesamt für Naturschutz, Umwelt und Geologie (HLNUG) | Datenlizenz Deutschland – Namensnennung 2.0 | OK, 2.4 s |
| `hlnug_starkregen` | Starkregen-Hinweis-Index und Vulnerabilität (1-km-Raster) sowie Fließpfade bei Starkregen. | HLNUG (mit DWD) | Datenlizenz Deutschland – Namensnennung 2.0 | OK, 1.3 s |

### Natur, Boden & Lärm

| ID | Was | Anbieter | Lizenz | Test |
|---|---|---|---|---|
| `hlnug_laerm` | Amtliche Lärmpegel LDEN (Tag-Abend-Nacht) und LNight am Punkt aus der EU-Umgebungslärmkartierung 2017 und 2022. | HLNUG | Datenlizenz Deutschland – Namensnennung 2.0 | OK, 0.7 s |
| `hlnug_schutzgebiete` | Naturschutz-, Landschaftsschutz-, FFH- und Vogelschutzgebiete, Naturdenkmale, Naturparke im Umkreis. | HLNUG (NATUREG) | Datenlizenz Deutschland – Namensnennung 2.0 | OK, 1.3 s |
| `hlnug_wasserschutz` | Wasserschutzgebiete mit Schutzzonen (I, II, III) – wichtig für Bauvorhaben und Versickerung. | HLNUG (GruSchu) | Datenlizenz Deutschland – Namensnennung 2.0 | OK, 0.5 s |
| `hlnug_biotope` | Gesetzlich geschützte Biotope, FFH-Lebensraumtypen, Streuobst und Gehölze aus Luftbildern. | HLNUG (Hessische Biotopkartierung) | Datenlizenz Deutschland – Namensnennung 2.0 | OK, 0.5 s |
| `hlnug_boden` | Boden am Punkt: Bodenhauptgruppe, Feldkapazität, nutzbare Feldkapazität (Wasserspeicher), Ertragspotenzial, Nitratrückhalt; dazu Karte der Bodenhauptgruppen. | HLNUG (Bodenflächendaten 1:50.000) | Datenlizenz Deutschland – Namensnennung 2.0 | OK, 1.1 s |
| `hlnug_geologie` | Geologische Einheit (GK25), Erdbebenzone, rutschungsanfällige und setzungsempfindliche Schichten, Karst, Erdfälle. | HLNUG (Geologischer Dienst) | Datenlizenz Deutschland – Namensnennung 2.0 | OK, 0.6 s |
| `hlnug_radon` | Radonpotenzial und Bodenluft-Prognose am Punkt (wichtig für Neubauten). | HLNUG / Bundesamt für Strahlenschutz | Datenlizenz Deutschland – Namensnennung 2.0 | OK, 0.4 s |
| `schutzgebiete_bund` | Bundesweite Schutzgebiete (NSG, LSG, FFH, Vogelschutz, Nationalparke, Naturparke) aus dem BfN-WFS, geladen mit GDAL/ogr2ogr aus QGIS. | Bundesamt für Naturschutz | Datenlizenz Deutschland – Namensnennung 2.0 | BfN in Wartung |
| `gbif_arten` | Beobachtete Tier- und Pflanzenarten im Umkreis seit einem Jahr: häufigste Arten, Rote-Liste-Kategorie (IUCN), Fundpunkte. Parameter: `ab_jahr` | Global Biodiversity Information Facility | je Datensatz CC0 / CC BY / CC BY-NC | OK, 4.2 s |

### Bevölkerung, Verwaltung & Energie

| ID | Was | Anbieter | Lizenz | Test |
|---|---|---|---|---|
| `verwaltungseinheit` | Name, Gemeindeschlüssel (AGS/ARS) und Grenze der Gemeinde, dazu Kreis und Land. | Bundesamt für Kartographie und Geodäsie | Datenlizenz Deutschland – Namensnennung 2.0 (© GeoBasis-DE / BKG) | OK, 0.4 s |
| `zensus2022` | Einwohner, Gebäude nach Zahl der Wohnungen (Ein-/Mehrfamilienhäuser) und Eigentümerquote im Umkreis, als 100-m-Karte. | Statistisches Bundesamt (Destatis) | Datenlizenz Deutschland – Namensnennung 2.0 | OK, 0.1 s |
| `ladesaeulen_register` | Gemeldete öffentliche Ladepunkte im Umkreis mit Leistung, AC/DC, Betreiber und Inbetriebnahme. | Bundesnetzagentur | CC BY 4.0 | OK, 0.0 s |
| `marktstammdaten` | Alle Stromerzeugungsanlagen der Gemeinde (PV, Wind, Biomasse, Speicher, BHKW ...) nach Energieträger, größere Anlagen mit Standort im Umkreis. | Bundesnetzagentur (MaStR) | Datenlizenz Deutschland – Namensnennung 2.0 | OK, 15.6 s |
| `strommix` | Stromerzeugung nach Energieträger, Anteil Erneuerbarer, Verbrauch und Börsenstrompreis. | Bundesnetzagentur (SMARD) | CC BY 4.0 | OK, 4.5 s |

### Satellit & Landbedeckung

| ID | Was | Anbieter | Lizenz | Test |
|---|---|---|---|---|
| `copernicus_versiegelung` | Anteil versiegelter Fläche je 10-m-Zelle (0-100 %, Stand 2018) als Karte und Kennzahlen. | Europäische Umweltagentur / Copernicus Land Monitoring Service | frei (Copernicus, © EU) | OK, 1.3 s |
| `copernicus_baumbedeckung` | Kronenbedeckung je 10-m-Zelle (0-100 %, Stand 2018) – erfasst auch Bäume, die in OSM fehlen. | Europäische Umweltagentur / Copernicus Land Monitoring Service | frei (Copernicus, © EU) | OK, 0.9 s |
| `esa_worldcover` | Landbedeckungsklassen (Bäume, Grünland, Acker, bebaut, Wasser ...) mit Flächenanteilen; direkt per GDAL aus der Cloud. | Europäische Weltraumorganisation (ESA) | CC BY 4.0 | OK, 0.6 s |
| `sentinel2_ndvi` | Vegetationsindex NDVI (10 m) aus der wolkenärmsten Sommeraufnahme: Grünanteil, versiegelte/kahle Flächen. Parameter: `von`, `bis`, `max_wolken` | ESA Copernicus Sentinel-2 über Element 84 Earth Search (AWS) | frei (Copernicus Sentinel-Daten) | OK, 6.0 s |
| `landsat_oberflaechentemperatur` | Gemessene Oberflächentemperatur (°C, 30 m) an einem klaren Sommertag (Überflug ca. 10:30 Uhr): Hitzeinseln sichtbar. Parameter: `von`, `bis`, `max_wolken` | USGS/NASA Landsat 8/9 über Microsoft Planetary Computer | gemeinfrei (USGS) | OK, 1.1 s |
| `gelaendehoehe` | Höhe am Punkt und auf einem 7x7-Raster im Umkreis: Hoch- und Tiefpunkte, Höhenunterschied. | Open-Meteo (Copernicus DEM 90 m), OpenTopoData (EU-DEM 25 m) | frei (Copernicus) / CC BY 4.0 | OK, 0.7 s |
| `karte_hessen` | Speichert einen Bildausschnitt (Luftbild 20 cm, Liegenschaftskarte ALKIS oder topografische Karte). Luftbild und ALKIS gibt es auch als Hintergrund in jeder Karte. Parameter: `ebene` | Hessische Verwaltung für Bodenmanagement und Geoinformation | Datenlizenz Deutschland – Zero 2.0 | OK, 1.0 s |

### Mobilität & Verkehr

| ID | Was | Anbieter | Lizenz | Test |
|---|---|---|---|---|
| `oepnv_haltestellen` | Haltestellen im Umkreis mit Verkehrsmitteln (Bus, Tram, S-Bahn, Zug) und Abstand. | Transitous (MOTIS) mit Fahrplänen von DELFI u.a. | Fahrplandaten je Verbund (meist CC BY 4.0 / DL-DE) | OK, 0.3 s |
| `oepnv_abfahrten` | Abfahrten an der nächstgelegenen Haltestelle (oder einer genannten) mit Linie, Ziel und Verspätung. Parameter: `haltestelle`, `anzahl` | Transitous (MOTIS) | Fahrplandaten je Verbund (meist CC BY 4.0 / DL-DE) | OK, 0.5 s |
| `erreichbarkeit` | Flächen, die in x Minuten zu Fuß, mit dem Rad oder dem Auto erreichbar sind (für Einzugsgebiete, Versorgung). Parameter: `modus`, `minuten` | FOSSGIS e.V. (Valhalla-Server, OpenStreetMap-Daten) | ODbL (OSM-Daten), faire Nutzung | OK, 0.7 s |
| `route` | Weg von lat/lon zu einem Ziel zu Fuß, mit dem Rad oder dem Auto: Länge, Zeit, Wegbeschreibung, Linie für die Karte. Parameter: `ziel_lat`, `ziel_lon`, `modus` | FOSSGIS e.V. (Valhalla-Server, OpenStreetMap-Daten) | ODbL (OSM-Daten), faire Nutzung | OK, 0.7 s |
| `autobahn` | Aktuelle Baustellen, Sperrungen und Verkehrsmeldungen (auch Lkw-Parkplätze, Ladestationen) im Umkreis. Parameter: `autobahnen`, `arten` | Die Autobahn GmbH des Bundes | Datenlizenz Deutschland – Namensnennung 2.0 | OK, 2.1 s |
| `bikesharing` | Leihrad-Stationen im Umkreis mit freien Rädern und Stellplätzen. | CityBikes API | CityBikes-Nutzungsbedingungen (frei, Namensnennung) | OK, 1.1 s |
| `unfallatlas` | Punktgenaue Unfälle mit Personenschaden: Anzahl je Jahr und Schwere, Beteiligte (Rad, Fuß, Pkw ...), Unfallarten, Häufungsstellen. Erster Aufruf lädt ca. 13 MB je Jahr. Parameter: `jahre` | Statistische Ämter des Bundes und der Länder | Datenlizenz Deutschland – Namensnennung 2.0 | OK, 4.0 s |

### Wissen & Orte

| ID | Was | Anbieter | Lizenz | Test |
|---|---|---|---|---|
| `wikipedia` | Artikel zu Orten im Umkreis (Gebäude, Plätze, Denkmäler, Geschichte) mit Kurztext. Parameter: `sprache` | Wikimedia Foundation | CC BY-SA 4.0 | OK, 3.7 s |
| `wikidata` | Objekte mit Koordinaten im Umkreis mit Typ (Schule, Kirche, Brunnen ...) und Denkmalstatus. | Wikimedia Foundation (Wikidata) | CC0 | OK, 1.9 s |

### Kataloge & beliebige Dienste

| ID | Was | Anbieter | Lizenz | Test |
|---|---|---|---|---|
| `datei_laden` | Lädt eine Datei per URL (z.B. aus opendata_darmstadt oder govdata), wandelt Shapefiles/CSV mit Koordinaten in GeoJSON. Parameter: `url` | je nach Quelle | je nach Datensatz | OK, 0.4 s |
| `opendata_darmstadt` | Städtische Datensätze: Verkehrszählungen der Ampeln (Rohdaten), statistische Bezirke, Bevölkerung, Wohnungen, Sozialatlas, Klima. Parameter: `suche`, `datensatz`, `url` | Wissenschaftsstadt Darmstadt | je Datensatz (meist DL-DE BY 2.0) | OK, 1.0 s |
| `govdata` | Suche in über 100.000 offenen Datensätzen von Bund, Ländern und Kommunen mit Download-Adressen. Parameter: `suche`, `url` | GovData (Bund, Länder, Kommunen) | je Datensatz | OK, 0.5 s |
| `geoportal_hessen` | Sucht WMS/WFS-Dienste von Land und Kommunen (Bebauungspläne, Bodenrichtwerte, Fachkarten ...). Parameter: `suche`, `typ` | Geoportal Hessen (Mapbender) | je Dienst | OK, 0.5 s |
| `wfs_abfrage` | Lädt Objekte eines WFS im Umkreis als GeoJSON (GDAL/ogr2ogr aus QGIS). Ohne layer: Liste der Ebenen. Parameter: `url`, `layer` | je nach Dienst | je nach Dienst | OK, 1.2 s |
| `arcgis_abfrage` | Objekte einer Ebene eines ArcGIS-MapServers/FeatureServers im Umkreis als GeoJSON (z.B. weitere HLNUG-Fachkarten). Ohne layer: Liste der Ebenen. Parameter: `url`, `layer` | je nach Dienst | je nach Dienst | OK, 5.3 s |
| `wms_abfrage` | Fragt den Wert einer WMS-Ebene am Punkt ab (z.B. aus geoportal_hessen gefundene Fachkarten). Parameter: `url`, `layer` | je nach Dienst | je nach Dienst | OK, 3.0 s |

## Plausibilität am Luisenplatz (Umkreis 500 m)

| Quelle | Wert |
|---|---|
| copernicus_versiegelung | 84 % versiegelt, 75 % der Fläche ≥ 80 % |
| copernicus_baumbedeckung / esa_worldcover | 1 % Kronendeckung (HRL 2018) bzw. 11 % „Bäume“ (WorldCover 2021, gröber klassifiziert) |
| landsat_oberflaechentemperatur | 48 °C Oberfläche im Mittel am 24.06.2026 (ca. 10:30 Uhr), Parks deutlich kühler |
| hlnug_hitze | 41 °C max. Landoberflächentemperatur, Hotspot „bis 10 °C wärmer“ |
| hlnug_starkregen | Starkregen-Hinweis-Index 4 und Vulnerabilität 4 (hoch) |
| kostra_starkregen | 1 Stunde: 15,7 mm (jährlich) bis 45,2 mm (100-jährlich) |
| hlnug_laerm | Straßenlärm 2022 ca. 52 dB(A) LDEN, Stadtbahn ca. 58 dB(A) |
| unfallatlas | 35 Unfälle mit Verletzten (2024), davon 18 mit Rad, 10 mit Fußgängern |
| zensus2022 | ca. 4.900 Einwohner, ca. 6.300 je km² |
| dwd_klimaraster | heiße Tage (≥ 30 °C) 2021-2025: 8, 41, 23, 19, 22; Mittel 1961-1990: 9, 1991-2020: 17 |

Die Werte passen zur Innenstadt. Zwei Quellen zum selben Thema können sich unterscheiden (Baumbedeckung HRL vs. WorldCover), deshalb soll der Agent mehrere Quellen nennen und vergleichen.

## Modus „Nur Datenquellen“

- Aus: Werkzeuge `hitze`, `starkregen`, `ladesaeulen`, `traffic_impact` und `construction_noise`.
  - Sie fehlen im Werkzeug-Angebot an das Modell (8 statt 13 Werkzeuge).
  - Zusätzlich sperrt `execute_tool` sie, falls ein Modell sie trotzdem aufruft.
- Der Systemprompt bekommt statt der Skill-Anleitungen eigene Regeln:
  - nur Daten und QGIS, keine Modelle „im Kopf“;
  - bei Was-wäre-wenn-Fragen den Ist-Zustand aus den Daten zeigen und die Richtung der Änderung begründen, ohne erfundene Zahlen;
  - am Ende eine Tabelle **„Annahmen“** (eigene Festlegungen wie Radius oder Zeitraum, mit Begründung) und eine Tabelle **„Datenquellen“**.
- In beiden Modi stehen alle Datenquellen zur Verfügung. Im Skill-Modus soll der Agent die Skills mit Daten ergänzen, etwa `kostra_starkregen` für `niederschlag_mm` oder `copernicus_baumbedeckung` als Gegenprobe zu den OSM-Bäumen.
- Unterschied in der Praxis bei „Wird es wärmer, wenn wir Bäume fällen?“:
  - **Nur Datenquellen** zeigt gemessene Werte (Oberflächentemperatur, Baumbedeckung, Wärmeinsel, heiße Tage) und erklärt die Richtung, liefert aber keine Zahl für die Änderung.
  - **Mit Skills** kommt dazu eine modellierte Abschätzung mit anpassbaren Annahmen.

Beispielfragen für den Modus stehen in der Seitenleiste, z.B. „Wie heiß wird es im Sommer am Luisenplatz Darmstadt und wie viel Grün gibt es dort?“

## Erkenntnisse aus den Tests

- **Overpass** (OSM online) war weiter überlastet (Zeitüberschreitung). Die lokale Geofabrik-Kopie bleibt wichtig.
- **db.transport.rest** antwortete mit 503. **Transitous** (DELFI-Fahrpläne, mit Echtzeit) funktioniert und ist eingebunden.
- Der **BfN-WFS** war während des Tests in Wartung. Für Hessen gibt es die gleichen Gebiete über `hlnug_schutzgebiete`.
- Der **HLNUG-Server** wird bei vielen gleichzeitigen Anfragen langsam (30-s-Zeitüberschreitungen, als 6 Quellen parallel liefen). Je Quelle laufen jetzt höchstens 3 Anfragen gleichzeitig. Die Lärmabfrage nutzt nur Rasterebenen, die langsame Vektorebene „Gesamtlärm“ ist ausgelassen.
- **GDAL-WFS-Treiber und BKG VG250**: Mit räumlichem Filter kommen 0 Objekte zurück. `wfs_abfrage` fragt dann direkt mit BBOX an und wandelt die Antwort mit ogr2ogr um.
- **Luftbild Hessen**:
  - Der Layer `he_dop20_rgb` liefert in Web-Mercator nur weiße Kacheln, deshalb wird `he_dop_rgb` genutzt.
  - Die Liegenschaftskarte erscheint erst bei starkem Zoom.
- **NetCDF über `/vsicurl/`** geht unter Windows nicht. Die UHI-Dateien (je ca. 140 KB) werden deshalb lokal gespeichert und dann mit GDAL gelesen.
- **Sentinel-2** (Earth Search) hat einen Offset von −0,1 auf die Reflexion. Ungültige Pixel werden vor dem NDVI ausgeblendet.
- **Valhalla**: Das JSON in der URL muss ohne Leerzeichen kodiert sein, sonst kommt „Failed to parse json“.
- **Datenqualität**, die der Agent nennen sollte:
  - Copernicus HRL hat den Stand 2018.
  - Landsat misst die Oberflächen- und nicht die Lufttemperatur, um ca. 10:30 Uhr.
  - ERA5 und CMIP6 sind grobe Raster.
  - Bürgersensoren sind nicht kalibriert.
  - MaStR hat Koordinaten nur für größere Anlagen.
  - Der Zensus liegt lokal nur für die Region `LOCAL_OSM_BBOX` vor.
  - GBIF enthält Zufallsfunde, keine Kartierung.

## Bewusst nicht eingebunden

| Quelle | Grund |
|---|---|
| OpenChargeMap, Tankerkönig, Mapillary, OpenAQ v3, RMV-API, DB API Marketplace | API-Key nötig |
| Destatis GENESIS / Regionalstatistik, Mobilithek | Login bzw. Registrierung nötig |
| Overture Maps, GHSL, WorldPop | sehr große Dateien, für kurze Abfragen zu langsam |
| Hessen LoD2-3D-Gebäude, ALKIS als Vektordaten | Download-Pakete, nicht geprüft (ALKIS als Karte ist eingebunden) |
| Darmstädter Verkehrsrohdaten | über `opendata_darmstadt` auffindbar (je Kreuzung eine ZIP mit Detektorzählungen), eigener Auswerter fehlt noch |

## Nächste Schritte

1. Mit dem LLM beide Modi mit denselben Fragen vergleichen: Wie gut kombiniert der Agent die Quellen ohne Skills?
2. Rasterquellen zusätzlich als GeoTIFF speichern, damit QGIS-Werkzeuge wie Zonenstatistik direkt darauf laufen.
3. Darmstädter Verkehrszählungen (Ampel-Detektoren) auswerten.
4. Für kleine Modelle den Systemprompt kürzen (zurzeit 13.000-17.000 Zeichen): nur Kategorien in den Prompt, Details über `datenquellen_katalog`.
