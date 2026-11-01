import json
import socket
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import TypeAdapter
from shapely.geometry import box, mapping, shape

from app.agent.language import detect_language
from app.main import create_app
from app.protocol.models import EVENT_MODELS, MapAction

MAP_ACTION = TypeAdapter(MapAction)

DARMSTADT_SQUARE = box(8.645, 49.870, 8.660, 49.880)
VIEWPORT = {
    "bbox": [8.63, 49.86, 8.67, 49.89],
    "center": [8.65, 49.875],
    "zoom": 15,
    "pitch": 0,
    "bearing": 0,
}

REGISTRY = """
- id: hessen-dop20
  title: { en: "Aerial imagery Hessen (DOP20)", de: "Luftbild Hessen (DOP20)" }
  provider: "HVBG"
  type: wms
  url: "https://www.gds-srv.hessen.de/cgi-bin/lika-services/ogc-free-images.ows"
  layers: [he_dop20_rgb]
  license: { name: "DL-DE Zero 2.0", url: "https://www.govdata.de/dl-de/zero-2-0" }
  attribution: "© HVBG"
  coverage: { name: "Hessen", bbox: [7.77, 49.39, 10.24, 51.66] }
  status: verified
  used_for: [basemap-aerial]
- id: openfreemap-liberty
  title: { en: "OpenStreetMap (OpenFreeMap)", de: "OpenStreetMap (OpenFreeMap)" }
  provider: "OpenFreeMap"
  type: vector-style
  url: "https://tiles.openfreemap.org/styles/liberty"
  license: { name: "ODbL 1.0", url: "https://opendatacommons.org/licenses/odbl/" }
  attribution: "OpenFreeMap © OpenMapTiles Data from OpenStreetMap"
  coverage: { name: "World", bbox: [-180, -85, 180, 85] }
  status: verified
  used_for: [basemap-osm]
- id: bayern-dop40
  title: { en: "Aerial imagery Bavaria (DOP40)", de: "Luftbild Bayern (DOP40)" }
  provider: "LDBV"
  type: wms
  url: "https://geoservices.bayern.de/od/wms/dop/v1/dop40"
  layers: [by_dop40c]
  license: { name: "CC BY 4.0", url: "https://creativecommons.org/licenses/by/4.0/" }
  attribution: "Bayerische Vermessungsverwaltung"
  coverage: { name: "Bayern", bbox: [8.97, 47.27, 13.84, 50.56] }
  status: verified
  used_for: [basemap-aerial]
"""


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """The mock agent must not make external calls: any outbound connection fails the test."""

    def refuse(*args, **kwargs):
        raise AssertionError("network access during a mock-agent test")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    registry = tmp_path / "registry.yaml"
    registry.write_text(REGISTRY, encoding="utf-8")
    monkeypatch.setenv("SOURCE_REGISTRY", str(registry))
    monkeypatch.setenv("MOCK_FAST", "1")
    monkeypatch.setenv("AGENT_MODE", "mock")
    return TestClient(create_app())


def parse_sse(body: str) -> list[tuple[str, dict]]:
    events = []
    for block in body.strip().split("\n\n"):
        lines = block.split("\n")
        assert lines[0].startswith("event: ") and lines[1].startswith("data: ") and len(lines) == 2, block
        events.append((lines[0][len("event: ") :], json.loads(lines[1][len("data: ") :])))
    return events


def chat(client, question, ui_language="en", selection=None, viewport=VIEWPORT):
    context = {"ui_language": ui_language, "viewport": viewport}
    if selection is not None:
        context["selection"] = {
            "type": "Feature",
            "geometry": mapping(selection),
            "properties": {"kind": "polygon"},
        }
    response = client.post(
        "/api/chat",
        json={
            "conversation_id": "c1",
            "messages": [{"role": "user", "content": question}],
            "context": context,
        },
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    return parse_sse(response.text)


def reply_text(events):
    return "".join(data["text"] for name, data in events if name == "text_delta")


def actions(events, kind=None):
    found = [data for name, data in events if name == "map_action"]
    return [a for a in found if kind is None or a["type"] == kind]


QUESTIONS = {
    "charging": "Where could new EV chargers go in this area?",
    "schools": "Show all schools in the selected area.",
    "area": "How large is this area and how much of it is green space?",
    "fly_to": "Fly to Fraunhofer IGD in Darmstadt and show the aerial image.",
    "data": "What data is available for this area?",
    "error_demo": "Simulate an error",
    "help": "Hello there",
}


@pytest.mark.parametrize("intent", QUESTIONS)
def test_event_order_and_schemas(client, intent):
    events = chat(client, QUESTIONS[intent], selection=DARMSTADT_SQUARE)
    names = [name for name, _ in events]

    assert names[0] == "run_start" and names.count("run_start") == 1
    assert names[-1] == "done" and names.count("done") == 1
    assert names.count("sources") <= 1
    # Every tool_start is closed by a tool_end with the same id, before any text is streamed.
    open_tools = []
    for name, data in events:
        if name == "tool_start":
            open_tools.append(data["id"])
        elif name == "tool_end":
            assert data["id"] == open_tools.pop()
        elif name == "text_delta":
            assert not open_tools
    assert not open_tools
    # Text comes in one contiguous block, after the tools and map actions.
    text_positions = [i for i, n in enumerate(names) if n == "text_delta"]
    if text_positions:
        assert text_positions == list(range(text_positions[0], text_positions[-1] + 1))
        assert all(n not in ("tool_start", "map_action") for n in names[text_positions[-1] :])
    # Every payload validates against its protocol model.
    for name, data in events:
        if name == "map_action":
            MAP_ACTION.validate_python(data)
        else:
            EVENT_MODELS[name].model_validate(data)


def test_english_question_gets_an_english_reply(client):
    events = chat(client, QUESTIONS["schools"], ui_language="de", selection=DARMSTADT_SQUARE)

    assert detect_language(reply_text(events)) == "en"


def test_german_question_gets_a_german_reply(client):
    events = chat(client, "Zeig alle Schulen im markierten Bereich.", selection=DARMSTADT_SQUARE)

    assert detect_language(reply_text(events)) == "de"


def test_other_language_gets_the_ui_language_and_a_note(client):
    events = chat(client, "Bonjour, où sont les écoles ?", ui_language="de")
    text = reply_text(events)

    assert detect_language(text) == "de"
    assert "Englisch und Deutsch" in text


def test_result_layer_lies_inside_the_selection_and_is_labelled(client):
    events = chat(client, QUESTIONS["schools"], selection=DARMSTADT_SQUARE)
    [layer] = actions(events, "add_geojson_layer")

    assert "Demo data" in layer["title"]
    assert layer["kind"] == "demo"
    assert layer["geojson"]["features"]
    for feature in layer["geojson"]["features"]:
        assert DARMSTADT_SQUARE.covers(shape(feature["geometry"]))
        assert feature["properties"]["source"] == "Demo data"
    assert actions(events, "fit_bounds")


def test_german_result_layer_title_says_demo_daten(client):
    events = chat(client, "Wo könnten in diesem Gebiet neue Ladesäulen hin?", selection=DARMSTADT_SQUARE)
    [layer] = actions(events, "add_geojson_layer")

    assert "Demo-Daten" in layer["title"]
    [highlight] = actions(events, "highlight_features")
    assert highlight["layer_id"] == layer["id"]
    assert highlight["feature_ids"]


def test_without_selection_features_land_in_the_viewport(client):
    events = chat(client, QUESTIONS["schools"])
    [layer] = actions(events, "add_geojson_layer")

    viewport = box(*VIEWPORT["bbox"])
    for feature in layer["geojson"]["features"]:
        assert viewport.covers(shape(feature["geometry"]))


def test_fly_to_igd_switches_to_aerial(client):
    events = chat(client, QUESTIONS["fly_to"])
    [fly] = actions(events, "fly_to")

    assert fly["center"][0] == pytest.approx(8.65, abs=0.02)
    assert fly["center"][1] == pytest.approx(49.875, abs=0.02)
    assert actions(events, "set_basemap") == [{"type": "set_basemap", "id": "aerial"}]


def test_fly_to_unknown_place_explains_instead_of_guessing(client):
    events = chat(client, "Fly to Atlantis")

    assert not actions(events, "fly_to")
    assert "Atlantis" in reply_text(events) or "know" in reply_text(events)


def test_area_reply_reports_the_geodesic_area(client):
    events = chat(client, "Wie groß ist das Gebiet und wie viel davon ist Grünfläche?", selection=DARMSTADT_SQUARE)
    text = reply_text(events)

    assert "km²" in text
    assert "1,2" in text  # the 0.015° x 0.010° square near Darmstadt is about 1.2 km²
    [layer] = actions(events, "add_geojson_layer")
    assert "Demo-Daten" in layer["title"]


def test_data_intent_lists_registry_sources_covering_the_area(client):
    events = chat(client, QUESTIONS["data"], selection=DARMSTADT_SQUARE)
    [sources] = [data for name, data in events if name == "sources"]
    titles = [item["title"] for item in sources["items"]]

    assert "Aerial imagery Hessen (DOP20)" in titles
    assert "Aerial imagery Bavaria (DOP40)" not in titles  # Bavaria does not cover Darmstadt
    assert not actions(events)


def test_error_demo_emits_a_retryable_error(client):
    events = chat(client, QUESTIONS["error_demo"])
    names = [name for name, _ in events]

    failed = [data for name, data in events if name == "tool_end" and data["status"] == "error"]
    assert failed
    [error] = [data for name, data in events if name == "error"]
    assert error["retryable"] is True
    assert names[-2:] == ["error", "done"]


def test_invalid_request_is_rejected(client):
    response = client.post("/api/chat", json={"conversation_id": "c1", "messages": []})

    assert response.status_code == 422


def test_llm_mode_reports_that_it_is_not_available_yet(client, monkeypatch):
    monkeypatch.setenv("AGENT_MODE", "llm")
    events = chat(TestClient(create_app()), "Hello")

    assert [name for name, _ in events] == ["run_start", "error", "done"]
    assert events[1][1]["retryable"] is False


TINY_SQUARE = box(8.65989, 49.87425, 8.65989 + 7e-6, 49.87425 + 4.5e-6)  # about 0.5 m x 0.5 m


@pytest.mark.parametrize("intent", [i for i in QUESTIONS if i != "error_demo"])
def test_a_tiny_selection_still_gets_a_clean_answer(client, intent):
    events = chat(client, QUESTIONS[intent], selection=TINY_SQUARE)
    names = [name for name, _ in events]

    assert names[-1] == "done"
    assert "error" not in names, [data for name, data in events if name == "error"]
    assert reply_text(events)
