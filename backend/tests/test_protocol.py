import pytest
from pydantic import TypeAdapter, ValidationError

from app.protocol.models import (
    EVENT_MODELS,
    ChatRequest,
    MapAction,
    TextDelta,
    ToolEnd,
)
from app.protocol.sse import format_sse

# A complete example request.
EXAMPLE_REQUEST = {
    "conversation_id": "uuid",
    "messages": [{"role": "user", "content": "..."}],
    "context": {
        "ui_language": "en",
        "viewport": {
            "bbox": [8.64, 49.86, 8.66, 49.88],
            "center": [8.65, 49.87],
            "zoom": 16,
            "pitch": 0,
            "bearing": 0,
        },
        "selection": {
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": []},
            "properties": {"kind": "polygon", "area_m2": 420000},
        },
        "active_layers": ["basemap:osm", "overlay:terrain"],
        "uploads": [
            {
                "id": "u1",
                "name": "parks.geojson",
                "feature_count": 12,
                "bbox": [],
                "geometry_types": ["Polygon"],
                "sample_properties": {},
            }
        ],
    },
}

MAP_ACTION = TypeAdapter(MapAction)

# One example per map action.
MAP_ACTIONS = [
    {"type": "fly_to", "center": [8.65, 49.87], "zoom": 16},
    {"type": "fit_bounds", "bbox": [8.64, 49.86, 8.66, 49.88]},
    {
        "type": "add_geojson_layer",
        "id": "result-1",
        "title": "Schools (Demo data)",
        "geojson": {"type": "FeatureCollection", "features": []},
        "color": "#2563eb",
        "kind": "demo",
    },
    {"type": "remove_layer", "id": "result-1"},
    {"type": "set_layer_visibility", "id": "result-1", "visible": False},
    {"type": "highlight_features", "layer_id": "result-1", "feature_ids": ["f1", "f2"]},
    {
        "type": "add_wms_layer",
        "id": "wms-1",
        "title": "Aerial imagery Hessen",
        "url": "https://example.org/wms",
        "layers": ["he_dop20_rgb"],
        "attribution": "© HVBG",
    },
    {"type": "set_basemap", "id": "aerial"},
    {"type": "set_view_mode", "mode": "3d"},
]


def test_example_request_validates():
    request = ChatRequest.model_validate(EXAMPLE_REQUEST)

    assert request.context.ui_language == "en"
    assert request.context.viewport is not None
    assert request.context.viewport.zoom == 16
    assert request.context.selection is not None
    assert request.context.selection.properties["kind"] == "polygon"
    assert request.context.uploads[0].name == "parks.geojson"


def test_minimal_request_gets_default_context():
    request = ChatRequest.model_validate({"conversation_id": "c1", "messages": [{"role": "user", "content": "Hi"}]})

    assert request.context.ui_language == "en"
    assert request.context.selection is None
    assert request.context.uploads == []


def test_request_without_messages_is_rejected():
    with pytest.raises(ValidationError):
        ChatRequest.model_validate({"conversation_id": "c1", "messages": []})


def test_format_sse_done_event():
    assert format_sse("done", {}) == "event: done\ndata: {}\n\n"


def test_format_sse_keeps_data_on_one_line_and_umlauts_readable():
    out = format_sse("text_delta", TextDelta(text="Größe\nzweite Zeile"))

    assert out == 'event: text_delta\ndata: {"text":"Größe\\nzweite Zeile"}\n\n'


@pytest.mark.parametrize("action", MAP_ACTIONS, ids=lambda a: a["type"])
def test_every_map_action_validates(action):
    parsed = MAP_ACTION.validate_python(action)

    assert parsed.type == action["type"]


def test_unknown_map_action_type_is_rejected():
    with pytest.raises(ValidationError):
        MAP_ACTION.validate_python({"type": "explode", "id": "x"})


def test_tool_end_status_must_be_ok_or_error():
    with pytest.raises(ValidationError):
        ToolEnd(id="t1", status="maybe", summary="", duration_ms=5)


def test_event_models_cover_exactly_the_protocol_events():
    assert set(EVENT_MODELS) == {
        "run_start",
        "text_delta",
        "tool_start",
        "tool_end",
        "map_action",
        "sources",
        "error",
        "done",
    }
