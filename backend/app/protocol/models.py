"""Agent protocol: the chat request and the SSE event payloads.

The frontend mirrors these types in `frontend/src/api/protocol.ts`; change both together.
"""

from typing import Annotated, Any, Literal, NamedTuple

from pydantic import BaseModel, ConfigDict, Field

LonLat = tuple[float, float]
BBox = tuple[float, float, float, float]  # west, south, east, north (WGS84)

Language = Literal["en", "de"]
BasemapId = Literal["osm", "official", "light", "relief", "aerial"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore")


# --- Request -------------------------------------------------------------------------------------


class Message(_Model):
    role: Literal["user", "assistant"]
    content: str


class Viewport(_Model):
    bbox: BBox
    center: LonLat
    zoom: float
    pitch: float = 0
    bearing: float = 0


class SelectionFeature(_Model):
    """The active map selection as a GeoJSON Feature; properties carry `kind` and `area_m2`."""

    type: Literal["Feature"] = "Feature"
    geometry: dict[str, Any]
    properties: dict[str, Any] = Field(default_factory=dict)


class UploadMeta(_Model):
    """Metadata of a user upload. No features are sent, only this summary."""

    id: str
    name: str
    feature_count: int = 0
    bbox: list[float] = Field(default_factory=list)
    geometry_types: list[str] = Field(default_factory=list)
    sample_properties: dict[str, Any] = Field(default_factory=dict)


class ChatContext(_Model):
    ui_language: Language = "en"
    viewport: Viewport | None = None
    selection: SelectionFeature | None = None
    active_layers: list[str] = Field(default_factory=list)
    uploads: list[UploadMeta] = Field(default_factory=list)


class ChatRequest(_Model):
    conversation_id: str
    messages: list[Message] = Field(min_length=1)
    context: ChatContext = Field(default_factory=ChatContext)


# --- Map actions ---------------------------------------------------------------------------------


class FlyTo(_Model):
    type: Literal["fly_to"] = "fly_to"
    center: LonLat
    zoom: float


class FitBounds(_Model):
    type: Literal["fit_bounds"] = "fit_bounds"
    bbox: BBox


class AddGeojsonLayer(_Model):
    type: Literal["add_geojson_layer"] = "add_geojson_layer"
    id: str
    title: str
    geojson: dict[str, Any]
    color: str
    # "demo": generated demo data (labelled as such in the UI); "result": real data.
    kind: Literal["result", "demo"]


class RemoveLayer(_Model):
    type: Literal["remove_layer"] = "remove_layer"
    id: str


class SetLayerVisibility(_Model):
    type: Literal["set_layer_visibility"] = "set_layer_visibility"
    id: str
    visible: bool


class HighlightFeatures(_Model):
    type: Literal["highlight_features"] = "highlight_features"
    layer_id: str
    feature_ids: list[str]


class AddWmsLayer(_Model):
    type: Literal["add_wms_layer"] = "add_wms_layer"
    id: str
    title: str
    url: str
    layers: list[str]
    attribution: str


class SetBasemap(_Model):
    type: Literal["set_basemap"] = "set_basemap"
    id: BasemapId


class SetViewMode(_Model):
    type: Literal["set_view_mode"] = "set_view_mode"
    mode: Literal["2d", "3d"]


MapAction = Annotated[
    FlyTo
    | FitBounds
    | AddGeojsonLayer
    | RemoveLayer
    | SetLayerVisibility
    | HighlightFeatures
    | AddWmsLayer
    | SetBasemap
    | SetViewMode,
    Field(discriminator="type"),
]


# --- Event payloads ------------------------------------------------------------------------------


class RunStart(_Model):
    run_id: str


class TextDelta(_Model):
    text: str


class ToolStart(_Model):
    id: str
    name: str
    label: str


class ToolEnd(_Model):
    id: str
    status: Literal["ok", "error"]
    summary: str
    duration_ms: int


class SourceItem(_Model):
    title: str
    url: str
    license: str


class Sources(_Model):
    items: list[SourceItem]


class ErrorEvent(_Model):
    message: str
    retryable: bool


class Done(_Model):
    pass


EventName = Literal["run_start", "text_delta", "tool_start", "tool_end", "map_action", "sources", "error", "done"]

# Payload model per event name. For `map_action` the data on the wire is the action itself.
EVENT_MODELS: dict[str, Any] = {
    "run_start": RunStart,
    "text_delta": TextDelta,
    "tool_start": ToolStart,
    "tool_end": ToolEnd,
    "map_action": MapAction,
    "sources": Sources,
    "error": ErrorEvent,
    "done": Done,
}


class AgentEvent(NamedTuple):
    """One event an agent yields: the SSE event name and its payload."""

    event: EventName
    data: BaseModel
