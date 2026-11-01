# Annahmen der eigenen Werkzeuge

Stand: 01.11.2026 · automatisch erzeugt aus dem Code (`*_DEFAULTS` in den Werkzeug-Modulen)

Alle Werte sind Standardwerte. Der Agent kann **jeden** davon über den Parameter `annahmen` ändern, z.B.
`{"kanal_mm": 25}` oder bei Einträgen mit mehreren Werten nur den geänderten: `{"gewichte_ac": {"netz": 0.4}}`.
Jedes Ergebnis enthält die Liste `annahmen`. Die Oberfläche zeigt sie vollständig unter der Antwort,
der Agent fasst die wichtigen (⭐) und die geänderten in einer Tabelle zusammen.

Nicht als Annahme geführt sind reine Darstellungswerte (Kartenfarben, Klassengrenzen der Legende) und technische Werte (Timeouts, Cache).

## Ladesäulen (`ladesaeulen`)

Quelle im Code: `ladeinfra_tools.DEFAULTS` (46 Annahmen)

| Name | Standard | Einheit | Bedeutung |
|---|---|---|---|
| ⭐ `pkw_je_einwohner` | 0.45 | Pkw/Einw. | Pkw je Einwohner (Deutschland ca. 0,58, Uni-Stadt weniger) |
| ⭐ `kwh_je_e_auto_tag` | 6.4 | kWh/Tag | Energiebedarf je E-Auto (13.000 km/Jahr x 0,18 kWh/km) |
| ⭐ `oeffentlich_laden_efh` | 0.1 | Anteil | öffentliches Laden bei Ein-/Zweifamilienhaus (eigene Wallbox) |
| ⭐ `oeffentlich_laden_mfh` | 0.6 | Anteil | öffentliches Laden bei Mehrfamilienhaus (kein eigener Stellplatz) |
| `oeffentlich_laden_max` | 0.9 | Anteil | Obergrenze öffentliches Laden je Zelle |
| `eigentuemer_effekt` | 0.4 | - | Eigentümer laden weniger öffentlich: Faktor (1 + e/2) - e x Eigentümerquote |
| `wohnungen_je_gebaeude` | 3bis6: 4.5, 7bis12: 9.5, 13plus: 20 | Whg. | Wohnungen je Gebäude in den Zensus-Klassen (Mittelwerte) |
| ⭐ `ziel_laden_anteil` | 0.15 | Anteil | Ziel-Laden (Einkaufen, Arbeit, Freizeit) am gesamten E-Auto-Bedarf |
| `ziel_gewichte` | supermarkt: 3, einkaufszentrum: 4, kaufhaus: 3, baumarkt: 2, uni: 4, hochschule: 2, klinik: 3, rathaus: 1, kino: 1.5, theater: 1, restaurant: 0.4, cafe: 0.2, sporthalle: 1.5, stadion: 2, schwimmbad: 1.5, fitness: 1, hotel: 2, park_and_ride: 3, buero: 0.3 | Gewicht | Gewicht je Zielart für die Verteilung des Ziel-Ladens |
| ⭐ `auslastung` | AC: 0.15, DC: 0.1 | Anteil | Ziel-Auslastung öffentlicher Ladepunkte über 24 h |
| `schnellladen_ab_kw` | 50 | kW | ab dieser Leistung gilt eine Station als Schnelllader |
| `osm_dublette_m` | 50 | m | OSM-Ladestation wird ignoriert, wenn BNetzA-Station so nah ist |
| `osm_kw_je_ladepunkt` | 11 | kW | Leistung je Ladepunkt bei OSM-Stationen ohne Angabe |
| ⭐ `einzugsbereich_m` | AC: 400, DC: 2000 | m | Einzugsbereich: zu Fuß (AC) bzw. kurzer Umweg (DC) |
| `dc_anteil_fuer_anwohner` | 0.5 | Anteil | wie stark Schnelllader den Wohn-Bedarf decken |
| `fahrten_start_wohnen` | 90 | Anzahl | Startpunkte der Simulation in Wohnzellen (nach Einwohnern) |
| `fahrten_start_rand` | 40 | Anzahl | Startpunkte am Gebietsrand (Durchgangsverkehr) |
| `ziele_je_start` | 12 | Anzahl | Ziele je Startpunkt |
| `rand_ab_radius_anteil` | 0.8 | Anteil | Knoten gelten als Rand ab diesem Anteil des Radius |
| `ziel_gewicht_faktor` | 3 | - | Gewicht von Zielen (POIs) bei der Zielwahl |
| `wohnen_als_ziel_faktor` | 0.02 | - | Gewicht von Wohnzellen (je Einwohner) bei der Zielwahl |
| `verkehr_suchradius_m` | 50 | m | Straßen in diesem Umkreis zählen für den Verkehrswert eines Standorts |
| `verkehr_normierung_perzentil` | 98 | % | Perzentil der Fahrten, das als Verkehrswert 1 gilt |
| `zufallsstart` | 42 | - | Startwert des Zufalls (gleich = gleiches Ergebnis) |
| `netz_ac_gut_bis_m` | 150 | m | AC: Netzwert 1 bis zu diesem Abstand zur Trafostation |
| `netz_ac_null_ab_m` | 600 | m | AC: Netzwert 0 ab diesem Abstand |
| `netz_dc_gut_bis_m` | 100 | m | DC: Netzwert 1 bis zu diesem Abstand |
| `netz_dc_null_ab_m` | 1000 | m | DC: Netzwert 0 ab diesem Abstand |
| `tiefbau_eur_je_m` | 150 | €/m | Kabel und Tiefbau innerorts für den Anschluss |
| `gleichzeitigkeit` | AC: 0.5, DC: 0.8 | Anteil | Gleichzeitigkeit der Ladepunkte für die Spitzenlast |
| ⭐ `neue_ladepunkte_kw` | AC: 11, DC: 150 | kW | Leistung je neuem Ladepunkt |
| `stellplaetze_schaetzung` | parkhaus: 200, flaeche: 25, strassenrand: 8, sonst: 20 | Stellpl. | Stellplätze, wenn OSM keine Kapazität angibt |
| `strassenrand_kandidaten` | 40 | Anzahl | Zellen mit größter Lücke, die als Straßenrand-Standort geprüft werden |
| `strassenrand_stellplaetze` | 6 | Stellpl. | Stellplätze eines Straßenrand-Standorts |
| `groesse_voll_ab_stellplaetze` | 50 | Stellpl. | ab so vielen Stellplätzen gilt der Größenwert 1 |
| ⭐ `gewichte_ac` | luecke: 0.55, netz: 0.2, groesse: 0.15, verkehr: 0.1 | Gewicht | Bewertung AC-Standort |
| ⭐ `gewichte_dc` | verkehr: 0.4, netz: 0.3, luecke: 0.2, groesse: 0.1 | Gewicht | Bewertung DC-Standort |
| `dc_max_anteil` | 0.25 | Anteil | höchstens dieser Anteil der Vorschläge wird Schnellladen |
| `mindestabstand_m` | 250 | m | Mindestabstand zwischen zwei Vorschlägen |
| `ladepunkte_ac` | min: 2, max: 10 | Anzahl | Ladepunkte je AC-Standort |
| `ladepunkte_dc` | min: 2, max: 4 | Anzahl | Ladepunkte je DC-Standort |
| `mindest_bewertung` | 0.05 | - | Standorte mit geringerer Bewertung werden nicht vorgeschlagen |
| `grund_luecke_gross` | 0.5 | - | Lückenwert ab dem 'große Versorgungslücke' genannt wird |
| `grund_luecke_mittel` | 0.2 | - | Lückenwert ab dem 'mittlere Versorgungslücke' genannt wird |
| `grund_verkehr` | 0.5 | - | Verkehrswert ab dem 'viel Verkehr' genannt wird |
| `grund_trafo_m` | 200 | m | Abstand bis zu dem die nahe Trafostation genannt wird |

## Starkregen (`starkregen`)

Quelle im Code: `climate_tools.STARKREGEN_DEFAULTS` (15 Annahmen)

| Name | Standard | Einheit | Bedeutung |
|---|---|---|---|
| ⭐ `niederschlag_mm` | 50 | mm in 1 h | Regenmenge (50 mm ca. 100-jährlicher Starkregen in Südhessen) |
| ⭐ `kanal_mm` | 10 | mm | was die Kanalisation von versiegelten Flächen aufnimmt |
| ⭐ `abflussbeiwert` | unbekannt: 0.45, wohngebiet: 0.5, gewerbe: 0.75, gruenflaeche: 0.25, acker_wiese: 0.3, wald: 0.1, wasser: 1, pflaster: 0.75, asphalt: 0.9, gebaeude: 0.9 | Anteil | Anteil des Regens, der oberirdisch abfließt, je Bodenart |
| `versiegelung` | unbekannt: 0.35, wohngebiet: 0.45, gewerbe: 0.8, gruenflaeche: 0, acker_wiese: 0, wald: 0, wasser: 0, pflaster: 0.9, asphalt: 1, gebaeude: 1 | Anteil | Versiegelungsgrad je Bodenart (Wohngebiet/Gewerbe = Rest ohne Gebäude und Straßen) |
| `strassenbreite_m` | motorway: 25, trunk: 16, primary: 12, secondary: 10, tertiary: 8, unclassified: 6, residential: 6, living_street: 5, service: 4, pedestrian: 6, busway: 7, track: 3, footway: 2, cycleway: 2, path: 1.5, steps: 2, bridleway: 2 | m | Breite je OSM-Straßenklasse |
| `gebiet_halbe_kante_m` | 1000 | m | Untersuchungsgebiet: halbe Kantenlänge des Quadrats |
| `rechenraster_m` | 4 | m | Rasterweite mit DGM1 (ohne DGM1 immer 10 m) |
| ⭐ `gebaeude_als_hindernis` | True | ja/nein | Gebäude ins Gelände einbrennen (nur mit DGM1) |
| `gebaeude_einbrennen_m` | 10 | m | so hoch werden Gebäude ins Gelände eingebrannt |
| `senke_min_tiefe_m` | 0.02 | m | Mulden flacher als das gelten nicht als Senke |
| ⭐ `pfuetze_bis_m2` | 100 | m² | kleinere Wasserflächen gelten als Pfütze (Gullys) und werden nicht gezählt |
| ⭐ `nass_ab_m` | 0.1 | m | Wassertiefe, ab der Fläche/Gebäude/Einrichtung als betroffen gilt |
| `mehr_wasser_ab_m` | 0.02 | m | Zunahme der Wassertiefe, ab der 'mehr Wasser' angezeigt wird |
| `einrichtung_umkreis_m` | 10 | m | Umkreis um sensible Einrichtungen für die Wassertiefe |
| `fliessweg_ab_ha` | klein: 3, mittel: 10, gross: 50 | ha | Einzugsgebiet ab dem Fließwege gezeigt werden |

## Hitze (`hitze`)

Quelle im Code: `climate_tools.HITZE_DEFAULTS` (15 Annahmen)

| Name | Standard | Einheit | Bedeutung |
|---|---|---|---|
| ⭐ `luft_versiegelung_k` | niedrig: 1, mittel: 2, hoch: 3 | K je 100 % | Wirkung von Versiegelung in der Nachbarschaft auf die Lufttemperatur |
| ⭐ `luft_baumkronen_k` | niedrig: 2, mittel: 3, hoch: 5 | K je 100 % | Kühlwirkung von Baumkronen in der Nachbarschaft |
| ⭐ `nachbarschaft_sigma_m` | 50 | m | Reichweite der Wirkung (Gauß, Sigma) |
| ⭐ `oberflaeche_c` | unbekannt: 38, wohngebiet: 38, gewerbe: 45, gruenflaeche: 33, acker_wiese: 35, wald: 27, wasser: 25, pflaster: 45, asphalt: 52, gebaeude: 45 | °C | Oberflächentemperatur je Bodenart an einem heißen Sommernachmittag |
| `baumschatten_c` | 29 | °C | Oberflächentemperatur im Baumschatten |
| `versiegelung` | unbekannt: 0.35, wohngebiet: 0.45, gewerbe: 0.8, gruenflaeche: 0, acker_wiese: 0, wald: 0, wasser: 0, pflaster: 0.9, asphalt: 1, gebaeude: 1 | Anteil | Versiegelungsgrad je Bodenart (Wohngebiet/Gewerbe = Rest ohne Gebäude und Straßen) |
| `strassenbreite_m` | motorway: 25, trunk: 16, primary: 12, secondary: 10, tertiary: 8, unclassified: 6, residential: 6, living_street: 5, service: 4, pedestrian: 6, busway: 7, track: 3, footway: 2, cycleway: 2, path: 1.5, steps: 2, bridleway: 2 | m | Breite je OSM-Straßenklasse |
| ⭐ `baumkrone_m` | 8 | m | Kronendurchmesser, wenn OSM keinen angibt |
| `baumkrone_radius_grenzen_m` | min: 2, max: 12 | m | Kronenradius wird auf diesen Bereich begrenzt |
| `baumreihe_breite_m` | 8 | m | Kronenbreite einer Baumreihe |
| `pflanzen_kronenanteil` | 0.6 | Anteil | Kronendeckung nach 'Bäume pflanzen' |
| `gebiet_halbe_kante_m` | 400 | m | Untersuchungsgebiet: halbe Kantenlänge des Quadrats |
| `zone_ab_k` | 0.1 | K | Temperaturänderung, ab der eine Fläche/ein Gebäude zur Zone zählt |
| `umgebung_radius_m` | 100 | m | Umkreis für Versiegelung/Kronen 'vorher/nachher' |
| `einrichtung_ab_k` | 0.05 | K | sensible Einrichtungen werden ab dieser Änderung genannt |

## Baustelle Verkehr (`traffic_impact`)

Quelle im Code: `impact_tools.VERKEHR_DEFAULTS` (7 Annahmen)

| Name | Standard | Einheit | Bedeutung |
|---|---|---|---|
| `untersuchungsradius_m` | 1500 | m | Straßennetz im Umkreis um die Baustelle |
| ⭐ `sperrung_m` | 30 | m | alle Straßenabschnitte bis zu diesem Abstand werden gesperrt |
| ⭐ `fahrten` | 1500 | Anzahl | simulierte Durchgangsfahrten |
| `rand_ab_radius_anteil` | 0.6 | Anteil | Start/Ziel der Fahrten liegen außerhalb dieses Anteils des Radius |
| `min_fahrtlaenge_anteil` | 1 | Anteil | Start und Ziel mindestens so weit auseinander (x Radius) |
| ⭐ `grundverkehr_faktor` | 1 | x Median | Grundverkehr je Abschnitt (Anwohner, Lieferverkehr) als Vielfaches des Medians |
| `zufallsstart` | 42 | - | Startwert des Zufalls (gleich = gleiches Ergebnis) |

## Baustelle Lärm (`construction_noise`)

Quelle im Code: `impact_tools.LAERM_DEFAULTS` (5 Annahmen)

| Name | Standard | Einheit | Bedeutung |
|---|---|---|---|
| ⭐ `schallleistung_db` | normal: 105, laut: 112, sehr_laut: 120 | dB(A) | Schallleistung Lw je Tätigkeit (Bagger/Lkw, Abbruch, Rammen) |
| ⭐ `bodendaempfung_db` | 8 | dB | Abzug für Punktquelle über Boden: L = Lw - 20 log10(r) - Abzug |
| `mindestabstand_m` | 5 | m | kleinster Abstand in der Formel (direkt an der Quelle) |
| `laermring_unterster_db` | 55 | dB(A) | unterster Lärmring; darüber 4 weitere in 5-dB-Schritten |
| ⭐ `richtwerte_db` | krankenhaus: 45, pflege: 45, soziale_einrichtung: 45, schule: 55, kita: 55, sonst: 55 | dB(A) | Immissionsrichtwerte tags (AVV Baulärm; Schule/Kita wie allg. Wohngebiet) |

Zusätzlich als normale Parameter: Ort (`lat`/`lon`), Größe (`radius_m`), Maßnahme bzw. Tätigkeit, beim Ladesäulen-Werkzeug `e_auto_anteil` und `anzahl`. Auch diese stehen in der Ergebnis-Tabelle.
