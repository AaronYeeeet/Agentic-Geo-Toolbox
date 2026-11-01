import pytest

from app.agent.language import detect_language

# Example questions.
ENGLISH_QUESTIONS = [
    "Where could new EV chargers go in this area?",
    "Show all schools in the selected area.",
    "How large is this area and how much of it is green space?",
    "Fly to Fraunhofer IGD in Darmstadt and show the aerial image.",
    "Which parking areas over 1,000 m² have no charger within 300 m?",
    "What data is available for this area?",
]
GERMAN_QUESTIONS = [
    "Wo könnten in diesem Gebiet neue Ladesäulen hin?",
    "Zeig alle Schulen im markierten Bereich.",
    "Wie groß ist das Gebiet und wie viel davon ist Grünfläche?",
    "Flieg zum Fraunhofer IGD in Darmstadt und zeig das Luftbild.",
    "Welche Parkplätze über 1.000 m² haben im Umkreis von 300 m keine Ladesäule?",
    "Welche Daten gibt es für dieses Gebiet?",
]


@pytest.mark.parametrize("question", ENGLISH_QUESTIONS)
def test_english_questions_are_english(question):
    assert detect_language(question) == "en"


@pytest.mark.parametrize("question", GERMAN_QUESTIONS)
def test_german_questions_are_german(question):
    assert detect_language(question) == "de"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Ladesäulen?", "de"),
        ("EV chargers Darmstadt", "en"),
        ("Hi", "en"),
        ("Hallo, was gibt es hier?", "de"),
        ("schools near me", "en"),
        ("Strasse und Gebiet", "de"),
        ("Show me Kölner Dom", "en"),
        ("Fly to München and show schools", "en"),
        ("Flieg nach Köln", "de"),
    ],
)
def test_short_and_keyword_only_questions(text, expected):
    assert detect_language(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "Bonjour, où sont les bornes ?",
        "¿Dónde hay escuelas?",
        "Dove sono le scuole in questa zona?",
        "Waar zijn de scholen in dit gebied?",
    ],
)
def test_other_languages_are_detected_as_other(text):
    assert detect_language(text) == "other"


@pytest.mark.parametrize("text", ["", "   ", "Darmstadt", "1234", "IGD?"])
def test_no_language_evidence_gives_none(text):
    assert detect_language(text) is None
