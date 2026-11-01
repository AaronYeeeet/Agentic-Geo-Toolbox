# E-Ladesäulen: Standortanalyse (Early Prototype)

Stand: 01.11.2026 · Branch `aaron-proto-ladesaeulen`

## Ziel

Der Agent soll Fragen wie diese beantworten:

> *"Wo könnten in Darmstadt-Mitte E-Ladesäulen sinnvoll sein?"*

Er führt dazu **Bedarf, Bestand, Verkehr und Stromnetz** zusammen und schlägt konkrete Standorte vor: Typ (AC-Normalladen / DC-Schnellladen), Zahl der Ladepunkte, Begründung.

**Kurzfazit:** Machbar und schnell (2–3 s pro Rechnung, offline). Bedarf und Bestand stützen sich auf **amtliche offene Daten** (Zensus 2022, Ladesäulenregister der Bundesnetzagentur). Die schwächsten Stellen sind das **Stromnetz**, denn Kapazitäten sind nicht öffentlich und wir kennen nur die Lage der Trafostationen aus OSM, sowie der **Verkehr**, der simuliert ist und nicht gezählt.

## Datenquellen

| Thema | Quelle | Was genau | Lizenz | Zugriff |
|---|---|---|---|---|
| Einwohner | [Zensus 2022](https://www.zensus2022.de) (Destatis) | Einwohner je 100-m-Zelle | Datenlizenz Deutschland 2.0 | ZIP, 18 MB |
| Wohnform | Zensus 2022 | Gebäude nach Anzahl Wohnungen (1, 2, 3–6, 7–12, 13+) je 100-m-Zelle | dto. | ZIP, 20 MB |
| Eigentum | Zensus 2022 | Eigentümerquote je 100-m-Zelle | dto. | ZIP, 17 MB |
| Bestand | [Ladesäulenregister BNetzA](https://www.bundesnetzagentur.de/ladeinfrastruktur) | alle gemeldeten öffentlichen Ladeeinrichtungen mit Ladepunkten, kW, Normal/Schnell, Betreiber | CC BY 4.0 (laut Drittquelle, nicht auf der BNetzA-Seite geprüft) | CSV, 55 MB, Stand 01.09.2026 |
| Bestand (Ergänzung) | OSM `amenity=charging_station` | nur wo die BNetzA im Umkreis von 50 m nichts kennt | ODbL | lokal |
| Ziele | OSM | Supermärkte, Einkaufszentren, Uni, Kliniken, Kino, Sport, Hotels, P+R, Büros | ODbL | lokal |
| Flächen | OSM `amenity=parking` | öffentliche bzw. Kundenparkplätze (ohne privat und Tiefgaragen) | ODbL | lokal |
| Verkehr | OSM-Straßennetz + Simulation | ca. 1.500 Fahrten Wohnen → Ziele sowie Durchgangsverkehr | ODbL | lokal |
| Stromnetz | OSM `power=substation/transformer` | Lage von Umspannwerken und Ortsnetzstationen (keine Kapazität) | ODbL | lokal |

Alle Rohdaten liegen in `data/` (nicht im Git). `ladeinfra_data.py` lädt fehlende Dateien und schneidet die Region aus (`LOCAL_OSM_BBOX`, ca. 9 s) nach `data/ladeinfra_*.pkl`. In der Region Darmstadt sind das 6.841 Zensus-Zellen (345.000 Einwohner) und 384 Ladeeinrichtungen mit 720 Ladepunkten. Zum Vergleich: OSM kennt im Stadtgebiet nur 61 Ladestationen, das amtliche Register ist also deutlich vollständiger.

### Geprüft, aber (noch) nicht nutzbar

| Quelle | Problem |
|---|---|
| **Netzkapazitäten** (e-netz Südhessen, [VNBdigital](https://www.vnbdigital.de)) | Freie Anschlusskapazitäten sind nicht öffentlich abrufbar. Laut gefundenen Quellen sind Kapazitätskarten der Netzbetreiber gesetzlich geplant (§ 17c EnWG-Entwurf), ob und ab wann verbindlich, ist offen. Bis dahin: Anfrage beim Netzbetreiber. |
| **Verkehrszählungen Darmstadt** ([opendata.darmstadt.de](https://opendata.darmstadt.de)) | Laut Statistik-Bulletin gibt es Rohdaten der Verkehrsdetektoren 2022–2025, minütlich. Struktur und Zugriff noch nicht geprüft. Wäre der nächste Schritt, um die Simulation zu kalibrieren. |
| Ladesäulenregister als Webservice | BNetzA bietet laut eigener Seite einen tagesaktuellen Webservice an; derzeit nutzen wir die monatliche CSV |

## Methode (`ladeinfra_tools.ladesaeulen`)

1. **Ladebedarf Wohnen** je 100-m-Zelle (kWh/Tag):
   Einwohner × 0,45 Pkw/Einwohner × E-Auto-Anteil × Anteil "muss öffentlich laden" × 6,4 kWh/Tag.
   - Anteil öffentlich: 10 % bei Ein-/Zweifamilienhäusern (eigene Wallbox) bis 60 % bei Mehrfamilienhäusern (kein eigener Stellplatz). Bei hoher Eigentümerquote weniger (Faktor 1,2 − 0,4 × Quote).
   - E-Auto-Anteil ist der Szenario-Regler. Standard 15 % (etwa 2030), heute ca. 5 %.
2. **Ladebedarf an Zielen:** zusätzlich 15 % des gesamten E-Auto-Bedarfs. Er wird nach Gewicht auf Supermärkte (3), Uni (4), Kliniken (3), Einkaufszentren (4), Sport (1,5), Hotels (2), P+R (3), Gastronomie (0,2–0,4) und Büros (0,3) verteilt.
3. **Bestand** in kWh/Tag: Leistung × 24 h × Auslastung (AC 15 %, DC 10 %).
4. **Versorgungsgrad je Ort** mit der **2-Step-Floating-Catchment-Area-Methode (2SFCA)**, einem Standardverfahren für Erreichbarkeit:
   - Schritt 1: Jede Ladestation teilt ihr Angebot durch den Bedarf in ihrem Einzugsbereich (AC 400 m Fußweg, DC 2 km), mit linear abnehmendem Gewicht nach Entfernung.
   - Schritt 2: Jeder Ort summiert die Quoten der erreichbaren Stationen. DC zählt fürs Wohnen nur zur Hälfte.
   - Lücke = Bedarf × (1 − Versorgungsgrad).
5. **Verkehr (Simulation):** 90 Startpunkte nach Einwohnern und 40 am Gebietsrand für Durchgangsverkehr, je 12 Ziele nach Gewicht. Gerechnet wird der kürzeste Weg auf dem lokalen OSM-Straßennetz. Daraus ergibt sich die Zahl der Fahrten je Straßenabschnitt.
6. **Stromnetz:** Abstand zur nächsten Trafostation bzw. zum nächsten Umspannwerk.
   - AC gut bis 150 m, schlecht ab 600 m. DC gut bis 100 m, schlecht ab 1 km, weil Schnelllader meist einen Mittelspannungsanschluss brauchen.
   - Grobe Anschlusskosten: Abstand × 150 €/m.
   - Zusätzliche Spitzenlast: Ladepunkte × kW × Gleichzeitigkeit (AC 0,5, DC 0,8), aufsummiert je Station.
7. **Standortwahl:**
   - Kandidaten sind öffentliche Parkplätze plus "Straßenrand" in den 40 Zellen mit der größten Lücke (Laternenladen).
   - Bewertung AC: 55 % Lücke, 20 % Netz, 15 % Größe, 10 % Verkehr.
   - Bewertung DC (nur an Hauptstraßen, höchstens ein Viertel der Vorschläge): 40 % Verkehr, 30 % Netz, 20 % Lücke, 10 % Größe.
   - **Schrittweise:** Der beste Kandidat wird gewählt, seine neuen Ladepunkte decken Bedarf in seinem Einzugsbereich, dann wird neu bewertet. Mindestabstand 250 m. So entsteht keine Häufung an einer Stelle.
   - Zahl der Ladepunkte = Lücke im Einzugsbereich / Leistung je Punkt (AC 2–10, DC 2–4).

Alle Annahmen stehen gesammelt oben in `ladeinfra_tools.py` und werden im Ergebnis mit ausgegeben.

## Testergebnisse (Darmstadt, Luisenplatz, Radius 1,5 km, ohne LLM)

| | 5 % E-Autos (heute) | 15 % E-Autos (Szenario) |
|---|---|---|
| Einwohner / E-Autos | 57.605 / 1.296 | 57.605 / 3.888 |
| öffentlicher Ladebedarf | 6.470 kWh/Tag | 19.411 kWh/Tag |
| vorhandene Ladepunkte (davon DC) | 151 (17) | 151 (17) |
| nicht gedeckt | 907 kWh/Tag ≈ **23 AC-Ladepunkte** | 9.724 kWh/Tag ≈ **246 AC-Ladepunkte** |
| Laufzeit | 3,1 s | 2,7 s |

Vorschläge bei 15 %:
- 2 Schnellladeknoten an Hauptstraßen: Dieburger Straße, Martinstraße.
- Sonst Normalladen in dicht bebauten Vierteln mit vielen Mehrfamilienhäusern: Kiesstraße und Roßdörfer Straße (Straßenrand), Riegerplatz, Ludwigsplatz/Hügelstraße, Elisabethenstraße.

Plausibel: Die Lücken liegen im Martinsviertel und in der östlichen Innenstadt, wo viele Menschen ohne eigenen Stellplatz wohnen.

**Test mit LLM** (*"Wo könnten in Darmstadt-Mitte E-Ladesäulen sinnvoll sein?"*):

- **Nemotron (OpenRouter):** Fehler 429, vermutlich das Tageslimit für Gratis-Anfragen. Nach 15 s kam der Hinweis, ein anderes Modell zu wählen.
- **Gemma 4 31B (Google):**
  - Ablauf korrekt: geocode → `ladesaeulen` (r = 1.500 m) → make_map mit den 5 Ebenen in der richtigen Reihenfolge.
  - Die Ergebnisse hat das Modell laut Denkprotokoll richtig zusammengefasst.
  - Die fertige Antwort kam wegen des Test-Timeouts (280 s) nicht mehr an, weil Google sehr langsam war (mehrfach Fehler 500, bis 134 s pro Schritt).
  - Protokoll: `output/logs/session_2026-11-01_13-32-24.md`.

## Grenzen

- **Stromnetz:** Wir kennen nur die Lage, nicht die freie Kapazität. Auch die Lage ist unvollständig: In OSM sind im Umfeld ca. 250 Stationen erfasst, real sind es deutlich mehr. "Trafostation 30 m entfernt" heißt nicht, dass dort Leistung frei ist.
- **Verkehr:** Simulation ohne echte Zählungen. Alle fahren den kürzesten Weg. Pendler von außerhalb und die Uhrzeit fehlen.
- **Annahmen** wie Pkw-Dichte, Anteil öffentlich Laden und Auslastung sind Größenordnungen, nicht für Darmstadt kalibriert.
- **Flächen** sind nicht auf Eigentum, Verfügbarkeit oder Denkmalschutz geprüft. Parkplätze aus OSM können privat sein, ohne dass es getaggt ist.
- **Zensus-Stand 2022,** Neubaugebiete danach fehlen.
- **Nur in der vorbereiteten Region** (`LOCAL_OSM_BBOX`), weil Zensus und BNetzA lokal ausgeschnitten werden.

## Nächste Schritte

1. **Verkehrsdaten Darmstadt** (Detektoren, Open Data) einlesen und die Simulation damit skalieren bzw. prüfen.
2. **Netzbetreiber anfragen** (e-netz Südhessen): Gibt es Kapazitätsdaten oder eine Liste der Ortsnetzstationen? Alternativ VNBdigital prüfen, sobald Kapazitätskarten veröffentlicht werden.
3. **KBA-Daten** zum tatsächlichen E-Auto-Bestand in Darmstadt (Zulassungen je Gemeinde) als Startwert für das Szenario.
4. **Auslastung echter Ladepunkte** (falls Betreiber Daten teilen) zur Kalibrierung der 2SFCA-Annahmen.
5. Kandidatenflächen mit städtischen Liegenschaften abgleichen.

## Testfragen

- *Wo könnten in Darmstadt-Mitte E-Ladesäulen sinnvoll sein?*
- *Wo fehlen in Darmstadt heute Ladesäulen, und wie sieht es bei 20 % E-Autos aus?*
- *Wo lohnt sich in Darmstadt ein Schnellladepark?*
