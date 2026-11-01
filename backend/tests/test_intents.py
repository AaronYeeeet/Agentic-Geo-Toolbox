import pytest

from app.agent.intents import detect_intent, wants_aerial


@pytest.mark.parametrize(
    ("text", "intent"),
    [
        # Example questions, EN and DE.
        ("Where could new EV chargers go in this area?", "charging"),
        ("Wo könnten in diesem Gebiet neue Ladesäulen hin?", "charging"),
        ("Show all schools in the selected area.", "schools"),
        ("Zeig alle Schulen im markierten Bereich.", "schools"),
        ("How large is this area and how much of it is green space?", "area"),
        ("Wie groß ist das Gebiet und wie viel davon ist Grünfläche?", "area"),
        ("Fly to Fraunhofer IGD in Darmstadt and show the aerial image.", "fly_to"),
        ("Flieg zum Fraunhofer IGD in Darmstadt und zeig das Luftbild.", "fly_to"),
        ("Which parking areas over 1,000 m² have no charger within 300 m?", "charging"),
        ("Welche Parkplätze über 1.000 m² haben im Umkreis von 300 m keine Ladesäule?", "charging"),
        ("What data is available for this area?", "data"),
        ("Welche Daten gibt es für dieses Gebiet?", "data"),
        # Keywords and variants.
        ("Where can I go charging my car?", "charging"),
        ("Wo kann ich mein Auto laden?", "charging"),
        ("Show me Kölner Dom", "fly_to"),
        ("Zeig mir Berlin", "fly_to"),
        ("Show me all schools here", "schools"),
        ("Find parking areas in this area", "charging"),
        ("Parkplätze im Gebiet", "charging"),
        ("Which datasets cover Hessen?", "data"),
        ("Simulate an error", "error_demo"),
        ("Fehler simulieren", "error_demo"),
        ("Hello there", "help"),
        ("", "help"),
    ],
)
def test_detect_intent(text, intent):
    assert detect_intent(text) == intent


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Fly to Fraunhofer IGD in Darmstadt and show the aerial image.", True),
        ("Flieg zum Fraunhofer IGD in Darmstadt und zeig das Luftbild.", True),
        ("Show me the satellite view of Darmstadt", True),
        ("Fly to Darmstadt", False),
    ],
)
def test_wants_aerial(text, expected):
    assert wants_aerial(text) is expected
