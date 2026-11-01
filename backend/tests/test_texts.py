import pytest

from app.agent.texts import fmt_area, fmt_length, fmt_percent, t


@pytest.mark.parametrize(
    ("m2", "lang", "expected"),
    [
        (8420, "en", "8,420 m²"),
        (15200, "de", "15.200 m²"),
        (99_000, "en", "99,000 m²"),
        (420_000, "de", "0,42 km²"),
        (1_200_000, "en", "1.20 km²"),
        (35_500_000, "de", "35,5 km²"),
        (357_000_000_000, "en", "357,000 km²"),
    ],
)
def test_fmt_area_uses_m2_below_a_tenth_of_a_km2(m2, lang, expected):
    assert fmt_area(m2, lang) == expected


def test_fmt_length_and_percent():
    assert fmt_length(850, "en") == "850 m"
    assert fmt_length(2600, "de") == "2,6 km"
    assert fmt_percent(0.18, "de") == "18 %"
    assert fmt_percent(0.18, "en") == "18%"


@pytest.mark.parametrize(
    ("lang", "key", "expected"),
    [
        ("en", "summary.charging_points", "1 existing charging point nearby (demo data)"),
        ("de", "summary.charging_points", "1 bestehender Ladepunkt in der Nähe (Demo-Daten)"),
        ("en", "summary.osm_schools", "1 school (demo data)"),
        ("de", "summary.osm_parking", "1 Parkplatz (Demo-Daten)"),
    ],
)
def test_counts_of_one_use_the_singular(lang, key, expected):
    assert t(lang, key, n=1) == expected


def test_counts_above_one_use_the_plural():
    assert t("de", "summary.charging_points", n=3) == "3 bestehende Ladepunkte in der Nähe (Demo-Daten)"
