"""User-facing strings of the mock agent in English and German, plus number formatting per language."""

from typing import Literal

Lang = Literal["en", "de"]


def fmt_number(value: float, lang: Lang, decimals: int = 0) -> str:
    text = f"{value:,.{decimals}f}"
    if lang == "de":
        text = text.replace(",", "\0").replace(".", ",").replace("\0", ".")
    return text


def fmt_area(m2: float, lang: Lang) -> str:
    """m² below 0.1 km², else km² (2, 1 or 0 decimals). Same rule as the frontend's formatArea."""
    if m2 < 100_000:
        return f"{fmt_number(m2, lang)} m²"
    km2 = m2 / 1_000_000
    decimals = 2 if km2 < 10 else 1 if km2 < 100 else 0
    return f"{fmt_number(km2, lang, decimals)} km²"


def fmt_length(meters: float, lang: Lang) -> str:
    if meters < 1000:
        return f"{fmt_number(meters, lang)} m"
    return f"{fmt_number(meters / 1000, lang, 1)} km"


def fmt_percent(share: float, lang: Lang) -> str:
    return f"{fmt_number(share * 100, lang)} %" if lang == "de" else f"{fmt_number(share * 100, lang)}%"


_TEXTS: dict[str, dict[str, str]] = {
    "en": {
        "kind.polygon": "polygon",
        "kind.rectangle": "rectangle",
        "kind.feature": "map feature",
        "kind.view": "map view",
        "kind.search": "search result",
        "tool.area.selection": "Reading the selected area",
        "tool.area.viewport": "Using the current map view as the area",
        "tool.area.default": "Using the default area around Fraunhofer IGD",
        "tool.osm_parking": "Searching OpenStreetMap for parking areas",
        "tool.charging_points": "Checking public charging points (Bundesnetzagentur)",
        "tool.rank_sites": "Ranking candidate sites",
        "tool.osm_schools": "Searching OpenStreetMap for schools",
        "tool.area_stats": "Measuring area and perimeter",
        "tool.land_cover": "Estimating green space (demo land cover)",
        "tool.geocode": "Looking up “{place}”",
        "tool.aerial": "Switching to aerial imagery",
        "tool.list_sources": "Checking the source registry for this area",
        "tool.overpass": "Querying OpenStreetMap (Overpass)",
        "summary.osm_parking": "{n} parking areas (demo data)",
        "summary.charging_points": "{n} existing charging points nearby (demo data)",
        "summary.rank_sites": "{n} candidates without a charger within 300 m",
        "summary.osm_schools": "{n} schools (demo data)",
        "summary.area_stats": "{area}, perimeter {perimeter}",
        "summary.land_cover": "{share} green space in {n} patches (demo data)",
        "summary.geocode_missing": "Not in the demo gazetteer",
        "summary.aerial_uncovered": "No open aerial imagery here yet",
        "summary.list_sources": "{n} verified sources cover this area",
        "summary.overpass_busy": "Overpass is busy (simulated)",
        "error.overpass_busy": "Overpass is busy. Try again in a minute.",
        "error.llm_unavailable": "LLM mode is not available in iteration 0. Set AGENT_MODE=mock.",
        "error.internal": "The agent stopped unexpectedly. Please try again.",
        "layer.charging": "EV charging candidates (Demo data)",
        "layer.schools": "Schools (Demo data)",
        "layer.green": "Green space (Demo data)",
        "name.parking": "Parking area",
        "name.school": "Demo school",
        "name.green": "Green space",
        "where.selection": "your selection ({area})",
        "where.viewport": "the current map view",
        "where.default": "the area around Fraunhofer IGD",
        "from.selection": "your selection",
        "from.viewport": "the current map view",
        "from.default": "the default area",
        "reply.charging": (
            "I found {n} parking areas in {where} that could host new chargers. None of them has a public "
            "charging point within 300 m. The best candidates are:\n{items}\n\nThese are **demo data** from the "
            "iteration-0 mock agent; iteration 1 will query OpenStreetMap and the Bundesnetzagentur register."
        ),
        "item.parking": "- {name}: {area}, about {cars} cars, score {score}/100",
        "reply.charging_none": (
            "I found no parking area in {where} that is large enough for chargers. Try a larger area. "
            "(**Demo data**; iteration 1 will query OpenStreetMap.)"
        ),
        "reply.schools": (
            "I found {n} schools in {where}:\n{items}\n\nThese are **demo data**; iteration 1 will query OpenStreetMap."
        ),
        "item.school": "- {name} ({type}, about {pupils} pupils)",
        "reply.area": (
            "The area covers **{area}** with a perimeter of {perimeter}. About **{share}** of it is green space "
            "({n} patches) according to the demo land-cover estimate.\n\nArea and perimeter are computed from "
            "{source}; the green-space share is **demo data** until a land-cover tool is connected."
        ),
        "reply.fly_to": "Flying to **{name}**.",
        "reply.aerial_covered": " The basemap now shows aerial imagery ({source}).",
        "reply.aerial_uncovered": (
            " I switched to the aerial basemap, but there is no open aerial imagery for this place yet."
        ),
        "reply.aerial_only": "The basemap now shows aerial imagery where open data exists.",
        "reply.fly_to_unknown": (
            "I don't know “{place}” yet. The demo gazetteer knows {names}. Iteration 1 will look places up "
            "with Nominatim."
        ),
        "reply.fly_to_noplace": "Tell me where to go, for example “Fly to Kölner Dom”.",
        "reply.data": (
            "{n} verified sources cover {where}:\n{items}\n\nLater iterations add OpenStreetMap queries "
            "(Overpass), the Bundesnetzagentur charging register and a dataset search over GDI-DE and GovData."
        ),
        "reply.data_none": "No verified source covers {where} yet.",
        "item.group": "- {group}: {titles}",
        "group.basemap": "Basemaps",
        "group.aerial": "Aerial imagery",
        "group.terrain": "Terrain",
        "group.buildings": "Buildings",
        "group.search": "Search and geocoding",
        "group.other": "Other",
        "reply.help": (
            "I'm the demo geo assistant of iteration 0 and answer with clearly labelled demo data. Try:\n"
            "- “Where could new EV chargers go in this area?”\n"
            "- “Show all schools in the selected area.”\n"
            "- “How large is this area and how much of it is green space?”\n"
            "- “Fly to Fraunhofer IGD in Darmstadt and show the aerial image.”\n"
            "- “What data is available for this area?”\n\n"
            "Draw a rectangle or polygon first to ask about a specific area."
        ),
        "note.other_language": "I can answer in English and German only, so I'm replying in English.",
        "source.osm": "OpenStreetMap (simulated)",
        "source.bnetza": "Bundesnetzagentur charging register (simulated)",
        "source.geodesic": "Geodesic area on WGS84 (pyproj)",
        "source.land_cover": "Land cover (simulated)",
        "source.gazetteer": "OpenStreetMap (place coordinates)",
    },
    "de": {
        "kind.polygon": "Polygon",
        "kind.rectangle": "Rechteck",
        "kind.feature": "Kartenobjekt",
        "kind.view": "Kartenausschnitt",
        "kind.search": "Suchergebnis",
        "tool.area.selection": "Ausgewähltes Gebiet lesen",
        "tool.area.viewport": "Aktuellen Kartenausschnitt als Gebiet verwenden",
        "tool.area.default": "Standardgebiet um das Fraunhofer IGD verwenden",
        "tool.osm_parking": "OpenStreetMap nach Parkplätzen durchsuchen",
        "tool.charging_points": "Öffentliche Ladepunkte prüfen (Bundesnetzagentur)",
        "tool.rank_sites": "Standorte bewerten",
        "tool.osm_schools": "OpenStreetMap nach Schulen durchsuchen",
        "tool.area_stats": "Fläche und Umfang berechnen",
        "tool.land_cover": "Grünflächen schätzen (Demo-Landbedeckung)",
        "tool.geocode": "„{place}“ nachschlagen",
        "tool.aerial": "Auf Luftbild umschalten",
        "tool.list_sources": "Quellenverzeichnis für dieses Gebiet prüfen",
        "tool.overpass": "OpenStreetMap abfragen (Overpass)",
        "summary.osm_parking": "{n} Parkplätze (Demo-Daten)",
        "summary.charging_points": "{n} bestehende Ladepunkte in der Nähe (Demo-Daten)",
        "summary.rank_sites": "{n} Kandidaten ohne Ladepunkt im Umkreis von 300 m",
        "summary.osm_schools": "{n} Schulen (Demo-Daten)",
        "summary.area_stats": "{area}, Umfang {perimeter}",
        "summary.land_cover": "{share} Grünfläche in {n} Flächen (Demo-Daten)",
        "summary.geocode_missing": "Nicht im Demo-Ortsverzeichnis",
        "summary.aerial_uncovered": "Hier noch kein offenes Luftbild",
        "summary.list_sources": "{n} geprüfte Quellen decken dieses Gebiet ab",
        "summary.overpass_busy": "Overpass ist ausgelastet (simuliert)",
        "error.overpass_busy": "Overpass ist ausgelastet. Versuchen Sie es in einer Minute noch einmal.",
        "error.llm_unavailable": "Der LLM-Modus ist in Iteration 0 noch nicht verfügbar. Setzen Sie AGENT_MODE=mock.",
        "error.internal": "Der Agent wurde unerwartet beendet. Bitte versuchen Sie es noch einmal.",
        "layer.charging": "Ladesäulen-Kandidaten (Demo-Daten)",
        "layer.schools": "Schulen (Demo-Daten)",
        "layer.green": "Grünflächen (Demo-Daten)",
        "name.parking": "Parkplatz",
        "name.school": "Demo-Schule",
        "name.green": "Grünfläche",
        "where.selection": "Ihrer Auswahl ({area})",
        "where.viewport": "dem aktuellen Kartenausschnitt",
        "where.default": "dem Gebiet um das Fraunhofer IGD",
        "from.selection": "Ihrer Auswahl",
        "from.viewport": "dem aktuellen Kartenausschnitt",
        "from.default": "dem Standardgebiet",
        "reply.charging": (
            "Ich habe {n} Parkplätze in {where} gefunden, an denen neue Ladesäulen entstehen könnten. Keiner "
            "davon hat einen öffentlichen Ladepunkt im Umkreis von 300 m. Die besten Kandidaten sind:\n{items}\n\n"
            "Das sind **Demo-Daten** des Mock-Agenten aus Iteration 0; ab Iteration 1 fragt der Agent "
            "OpenStreetMap und das Ladesäulenregister der Bundesnetzagentur ab."
        ),
        "item.parking": "- {name}: {area}, etwa {cars} Stellplätze, Bewertung {score}/100",
        "reply.charging_none": (
            "In {where} habe ich keinen Parkplatz gefunden, der groß genug für Ladesäulen ist. Versuchen Sie ein "
            "größeres Gebiet. (**Demo-Daten**; ab Iteration 1 fragt der Agent OpenStreetMap ab.)"
        ),
        "reply.schools": (
            "Ich habe {n} Schulen in {where} gefunden:\n{items}\n\nDas sind **Demo-Daten**; ab Iteration 1 "
            "fragt der Agent OpenStreetMap ab."
        ),
        "item.school": "- {name} ({type}, etwa {pupils} Schülerinnen und Schüler)",
        "reply.area": (
            "Das Gebiet umfasst **{area}** bei einem Umfang von {perimeter}. Etwa **{share}** davon sind laut der "
            "Demo-Landbedeckung Grünflächen ({n} Flächen).\n\nFläche und Umfang sind aus {source} berechnet; der "
            "Grünflächenanteil sind **Demo-Daten**, bis ein Werkzeug für die Landbedeckung angebunden ist."
        ),
        "reply.fly_to": "Ich fliege zu **{name}**.",
        "reply.aerial_covered": " Die Grundkarte zeigt jetzt das Luftbild ({source}).",
        "reply.aerial_uncovered": (
            " Ich habe auf die Luftbild-Grundkarte umgeschaltet, aber für diesen Ort gibt es noch kein offenes "
            "Luftbild."
        ),
        "reply.aerial_only": "Die Grundkarte zeigt jetzt Luftbilder, wo offene Daten vorliegen.",
        "reply.fly_to_unknown": (
            "„{place}“ kenne ich noch nicht. Das Demo-Ortsverzeichnis kennt {names}. Ab Iteration 1 sucht der "
            "Agent Orte über Nominatim."
        ),
        "reply.fly_to_noplace": "Sagen Sie mir, wohin es gehen soll, zum Beispiel „Flieg zum Kölner Dom“.",
        "reply.data": (
            "{n} geprüfte Quellen decken {where} ab:\n{items}\n\nSpätere Iterationen ergänzen "
            "OpenStreetMap-Abfragen (Overpass), das Ladesäulenregister der Bundesnetzagentur und eine "
            "Datensatzsuche über GDI-DE und GovData."
        ),
        "reply.data_none": "Für {where} gibt es noch keine geprüfte Quelle.",
        "item.group": "- {group}: {titles}",
        "group.basemap": "Grundkarten",
        "group.aerial": "Luftbilder",
        "group.terrain": "Gelände",
        "group.buildings": "Gebäude",
        "group.search": "Suche und Geokodierung",
        "group.other": "Weitere",
        "reply.help": (
            "Ich bin der Demo-Geoassistent aus Iteration 0 und antworte mit klar gekennzeichneten Demo-Daten. "
            "Probieren Sie zum Beispiel:\n"
            "- „Wo könnten in diesem Gebiet neue Ladesäulen hin?“\n"
            "- „Zeig alle Schulen im markierten Bereich.“\n"
            "- „Wie groß ist das Gebiet und wie viel davon ist Grünfläche?“\n"
            "- „Flieg zum Fraunhofer IGD in Darmstadt und zeig das Luftbild.“\n"
            "- „Welche Daten gibt es für dieses Gebiet?“\n\n"
            "Zeichnen Sie zuerst ein Rechteck oder Polygon, um nach einem bestimmten Gebiet zu fragen."
        ),
        "note.other_language": "Ich antworte nur auf Englisch und Deutsch, daher auf Deutsch.",
        "source.osm": "OpenStreetMap (simuliert)",
        "source.bnetza": "Ladesäulenregister der Bundesnetzagentur (simuliert)",
        "source.geodesic": "Geodätische Fläche auf WGS84 (pyproj)",
        "source.land_cover": "Landbedeckung (simuliert)",
        "source.gazetteer": "OpenStreetMap (Ortskoordinaten)",
    },
}

# "where" for the data reply needs the accusative/nominative in German.
_TEXTS["en"]["subject.selection"] = "your selection ({area})"
_TEXTS["en"]["subject.viewport"] = "the current map view"
_TEXTS["en"]["subject.default"] = "the area around Fraunhofer IGD"
_TEXTS["de"]["subject.selection"] = "Ihre Auswahl ({area})"
_TEXTS["de"]["subject.viewport"] = "den aktuellen Kartenausschnitt"
_TEXTS["de"]["subject.default"] = "das Gebiet um das Fraunhofer IGD"

# Singular variants, picked by t() when n == 1.
_TEXTS["en"]["summary.osm_parking.one"] = "1 parking area (demo data)"
_TEXTS["en"]["summary.charging_points.one"] = "1 existing charging point nearby (demo data)"
_TEXTS["en"]["summary.rank_sites.one"] = "1 candidate without a charger within 300 m"
_TEXTS["en"]["summary.osm_schools.one"] = "1 school (demo data)"
_TEXTS["en"]["summary.land_cover.one"] = "{share} green space in 1 patch (demo data)"
_TEXTS["en"]["summary.list_sources.one"] = "1 verified source covers this area"
_TEXTS["de"]["summary.osm_parking.one"] = "1 Parkplatz (Demo-Daten)"
_TEXTS["de"]["summary.charging_points.one"] = "1 bestehender Ladepunkt in der Nähe (Demo-Daten)"
_TEXTS["de"]["summary.rank_sites.one"] = "1 Kandidat ohne Ladepunkt im Umkreis von 300 m"
_TEXTS["de"]["summary.osm_schools.one"] = "1 Schule (Demo-Daten)"
_TEXTS["de"]["summary.land_cover.one"] = "{share} Grünfläche in 1 Fläche (Demo-Daten)"
_TEXTS["de"]["summary.list_sources.one"] = "1 geprüfte Quelle deckt dieses Gebiet ab"

SCHOOL_TYPES: dict[str, list[str]] = {
    "en": ["Primary school", "Secondary school", "Gymnasium", "Comprehensive school", "Vocational school"],
    "de": ["Grundschule", "Realschule", "Gymnasium", "Gesamtschule", "Berufsschule"],
}


def t(lang: Lang, key: str, **values: object) -> str:
    table = _TEXTS[lang]
    if values.get("n") == 1 and f"{key}.one" in table:
        key = f"{key}.one"
    return table[key].format(**values)
