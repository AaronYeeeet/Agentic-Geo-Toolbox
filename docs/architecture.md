# Architecture & Design Notes

> Status: **working prototype** (branch `lorenz_prototyp`, Nov 2026).
> Sections 10 and 11 describe what was measured to work, what doesn't, and what
> is left to do.

## 1. Goal

A chat UI (with a map) where a user uploads data and writes prompts. An LLM
identifies the tools needed to fulfil the task, accessing public data providers
(Open Data Hessen, OpenStreetMap, WMS) and existing processing tools (GeoPandas
geoprocessing, an AI surface-classification model). Findings are documented
reproducibly.

## 2. Why "tools", not code generation

Two schools exist in the literature (see §12):

- **Code generation**: the LLM writes Python/PyQGIS and a sandbox executes it
  (LLM-Geo, GISclaw). Maximum flexibility, but harder to make safe, deterministic
  and reproducible.
- **Tool calling**: the LLM picks from a fixed catalogue of documented tools
  with typed parameters (GIS Copilot, multi-agent QGIS frameworks).

We chose **tool calling**. It fits the assignment's "identify the needed tools"
framing, is inspectable (every call is logged), safer, and maps cleanly onto
LLM function calling. Free code execution can be added later as *one*
additional tool if needed.

The price: the agent can only do what the catalogue offers. A request like
*"where could a new school be built?"* needs several tools (OSM data, distance
analysis, land-use filter, suitability scoring), and missing ones (e.g.
`difference`, `filter_by_attribute`) make the LLM improvise or give up. Growing
the catalogue is the main lever for capability (§11).

## 3. Big picture

```
 Browser (React + MapLibre)                       Backend (FastAPI, Python)
┌───────────────────────────┐   POST /api/chat   ┌──────────────────────────────────────┐
│ Chat.jsx   prompt, upload │ ─────────────────► │ api/chat.py → orchestrator.run()     │
│            event log      │ ◄───────────────── │   loop: llm.complete() ─► LLM API    │
│ MapView.jsx  layers       │  SSE event stream  │         ↓ tool_calls                 │
└───────────────────────────┘                    │         registry → tools/*.py        │
                                                 │         ↓ ToolResult                 │
                                                 │   Session (workspace.py): layers     │
                                                 └───────────────┬──────────────────────┘
                                                                 │ HTTP
                                  ┌──────────────────────────────┼─────────────────────────┐
                                  ▼                              ▼                         ▼
                        Overpass / Nominatim            GovData CKAN API          WMS servers
                        (OpenStreetMap, osmnx)          (Open Data Hessen)        (owslib / browser)
```

Three ideas carry the whole design:

1. **The LLM never sees geometry.** Tools keep data as GeoDataFrames in the
   session and return only a short text summary to the LLM (`"Fetched 85
   features … stored as layer 'layer_05af6c66'"`). The LLM refers to data by
   `layer_id`. This keeps token usage small and stops the model from inventing
   coordinates.
2. **Two outputs per tool.** A `ToolResult` has a `summary` (for the LLM) and
   `layers` (full GeoJSON for the map). The orchestrator routes each to the
   right place.
3. **Everything is an event.** The agent loop yields events (`tool_call`,
   `layer`, …) that are streamed to the browser *and* written to the trace
   file. UI and reproducibility log come from the same source.

## 4. Components

### Frontend (`frontend/src/`)

| File | Role |
|------|------|
| `main.jsx` | React entry point. |
| `App.jsx` | Layout (sidebar + map), creates the session, polls `/api/health`, shows warnings (backend down / no API key), keeps the layer list. |
| `Chat.jsx` | Message list, composer, file upload. Turns SSE events into chat bubbles; re-creates the session if the backend restarted. |
| `MapView.jsx` | MapLibre GL map with an OSM raster basemap (no API key). Adds GeoJSON layers as fill/line/circle depending on geometry type, WMS as raster tiles, zooms to new layers. Falls back to a message if WebGL is unavailable. |
| `api.js` | `fetch` wrappers. `streamChat` reads SSE over a POST response by hand (the browser's `EventSource` only supports GET). |
| `vite.config.js` | Dev server on :5173, proxies `/api` to :8000 so there is one origin (no CORS issues in dev). |

### Backend (`backend/app/`)

| File | Role |
|------|------|
| `main.py` | FastAPI app, CORS, routers, `/api/health` (model, `llm_configured`, tool list). |
| `config.py` | Settings from `.env` via pydantic-settings. |
| `workspace.py` | `Session` (layers + LLM message history, in memory) and `Layer` (GeoDataFrame + metadata, `to_descriptor()` for the frontend). Writes traces to disk. |
| `api/chat.py` | `POST /sessions`, `GET /sessions/{id}/layers`, `POST /chat` (SSE). |
| `api/upload.py` | `POST /sessions/{id}/upload`: reads any GDAL-readable vector file into a layer and notes it in the LLM history. |
| `agent/orchestrator.py` | **The agent loop** (see §7). |
| `agent/llm.py` | The only provider-specific code (LiteLLM). |
| `agent/registry.py` | `@tool` decorator, `ToolResult`, export of JSON schemas for function calling. |
| `agent/prompts.py` | System prompt: role, working style, known data sources. |
| `agent/tools/*.py` | The tool catalogue (below). |
| `scripts/smoke_test.py` | Runs every tool without the LLM. |

### Tools (`backend/app/agent/tools/`)

| Tool | Purpose | Backed by | Status |
|------|---------|-----------|--------|
| `fetch_osm` | OSM features by place name or bbox + tags | osmnx → Overpass API | ✅ works, **slow** (30–100 s uncached), cached afterwards, falls back to Overpass mirrors |
| `wms_capabilities` | list layers of a WMS | owslib | ✅ |
| `add_wms_layer` | raster overlay on the map | browser loads the tiles itself | ✅ (Hessen DOP tested) |
| `search_open_data` | search GovData/Open Data Hessen | CKAN API | ⚠️ works, but most hits are HTML pages/PDFs, rarely direct vector data |
| `load_geodata_from_url` | load GeoJSON/GPKG/SHP-zip/WFS by URL | GeoPandas/GDAL | ✅ if the URL really points to vector data |
| `buffer` | buffer in metres (UTM), optional `dissolve` | GeoPandas | ✅ |
| `clip`, `intersection` | overlay of two layers | GeoPandas | ✅ |
| `centroids` | feature centroids | GeoPandas | ✅ |
| `layer_stats` | count, area/length, bbox | GeoPandas | ✅ |
| `classify_surface` | land-cover shares | **stub**: hash-based fake numbers | 🚧 interface only |
| `list_layers`, `show_layer` | layer introspection / display | — | ✅ |

## 5. Data model

**Session** (`workspace.py`): `id`, `layers: dict[layer_id → Layer]`,
`history: list[message]` (the full LLM conversation incl. tool results). Lives
in a Python dict, so **a backend restart loses all sessions**. The frontend
detects the 404 and creates a new one.

**Layer**: `id`, `name`, `source` (`osm`, `upload`, `buffer`, …), `gdf`
(GeoDataFrame, stored in WGS84).

**Layer descriptor** (what the frontend receives), from `Layer.to_descriptor()`:

```json
{ "id": "layer_05af6c66", "name": "Schulen", "source": "osm",
  "kind": "geojson", "geometry_type": "polygon", "feature_count": 85,
  "bounds": [8.61, 49.80, 8.69, 49.93], "geojson": { "type": "FeatureCollection", "...": "..." } }
```

WMS layers use `"kind": "wms-raster"` with a `tile_url` containing MapLibre's
`{bbox-epsg-3857}` placeholder instead of GeoJSON. They are not stored in the
session, so tools cannot process them.

**ToolResult** (`registry.py`): `summary: str` → LLM, `layers: list[descriptor]` → map.

## 6. API & event protocol

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/health` | `{status, model, llm_configured, tools[]}` |
| POST | `/api/sessions` | → `{session_id}` |
| GET | `/api/sessions/{id}/layers` | all layer descriptors of a session |
| POST | `/api/sessions/{id}/upload` | multipart `file` → `{layer}` |
| POST | `/api/chat` | `{session_id, message}` → `text/event-stream` |

Each SSE message is `data: <json>\n\n`. Event types, in typical order:

| `type` | Fields | Meaning |
|--------|--------|---------|
| `user` | `content` | echo of the prompt |
| `assistant_thought` | `content` | text the LLM wrote alongside tool calls (its plan) |
| `tool_call` | `name`, `arguments` (JSON string) | a tool is about to run |
| `layer` | `layer` (descriptor) | a new map layer |
| `tool_result` | `name`, `summary` | what the LLM gets back |
| `assistant_message` | `content` | final answer, the loop ends |
| `error` | `message` | LLM/API error (tool errors are *not* errors, they go back to the LLM) |
| `done` | — | stream end (always sent) |

## 7. The agent loop (`orchestrator.run`)

```
history = [system prompt, …earlier turns…, user message]
repeat up to AGENT_MAX_STEPS (default 12):
    msg = LLM(history, tool schemas)
    append msg to history
    if msg has no tool calls → emit assistant_message, stop
    for each tool call:
        emit tool_call
        result = tool(session, **args)      # exceptions → "ERROR …" summary
        emit layer(s), tool_result
        append {"role": "tool", content: result.summary} to history
write trace; emit done
```

Notes:
- **Errors are fed back to the LLM**, not shown as failures. A wrong `layer_id`
  returns `ERROR running layer_stats: Unknown layer_id …. Known layers: …`, and
  the LLM can correct itself on the next step. This self-repair is a large part
  of why agents work at all.
- History persists across turns, so follow-ups like *"now buffer that by 500 m"*
  work. It also grows without bound (every tool summary stays in it), so long
  sessions get slower and more expensive.
- The loop is synchronous; FastAPI runs it in a thread pool. Fine for one user.

## 8. The LLM layer

`agent/llm.py` calls `litellm.completion(model=LLM_MODEL, tools=…, tool_choice="auto")`.
LiteLLM translates the OpenAI-style tool schema into each provider's format, so
switching Claude ↔ Ollama is a `.env` change.

Provider notes learned while building the prototype:
- **Claude** (`anthropic/claude-opus-5-5`, `anthropic/claude-sonnet-5-5`, …):
  best tool planning. Current models reject `temperature`, so it is only sent
  to local models. Claude thinks before calling tools; its `thinking_blocks`
  must be sent back unchanged in the next request, which `_assistant_to_dict`
  does.
- **Gemini** (`gemini/gemini-3.5-flash`, free tier, tested Nov 2026): plans
  multi-step tool chains correctly (e.g. buffer with `dissolve` → `layer_stats`),
  ~2–4 s per step. Free tier = 5 requests/minute and 20 requests/day per model:
  `llm.complete` retries a per-minute 429 after the delay Google names and
  fails fast with a clear error once the daily quota is used up.
- **Local (Ollama)**: free and offline, but needs a model trained for tool
  calling (e.g. `qwen2.5`, `llama3.1`). Small models often pick wrong tools,
  invent `layer_id`s or stop after one step. Use `ollama_chat/<model>`.
- **LiteLLM ≥ 1.106** imports the `mcp` package whenever `tools` are passed but
  does not declare it, giving `No module named 'mcp'`. Hence `mcp` in
  `requirements.txt`.

## 9. Reproducibility strategy

| Measure | Status |
|---------|--------|
| **Trace per turn**: `workspace/<session>/traces/trace_<ts>.json` with every event (prompt, tool, arguments, summaries, layers), each with `t` = seconds since the turn started. Rewritten after every event, so running and aborted turns (`aborted` event) are visible too. The session folder appears on disk with the first trace. | ✅ |
| **Pinned deps**: `requirements.txt` (lower bounds only, use `pip freeze > requirements.lock` for exact pins) + `package-lock.json` | ⚠️ Python not exactly pinned |
| **OSM cache**: `workspace/osm_cache/` stores raw Overpass responses, so identical queries return identical data | ✅ |
| **Deterministic LLM**: `temperature=0` for local models; not available on current Claude models | ⚠️ LLM decisions can vary between runs, so the trace is the record |
| **Session workspaces**: uploads + traces per session on disk | ✅ (layers themselves are not saved) |

Traces are large because `layer` events contain full GeoJSON. That is useful
(the result is reproducible from the trace alone) but a city of buildings can
reach several MB.

## 10. What works well / what doesn't

Measured with `scripts/smoke_test.py` and manual tests (Nov 2026):

**Works well**
- Geoprocessing is fast (< 0.2 s) and correct, including metric buffers via automatic UTM.
- Tool catalogue + error feedback: the LLM sees clear errors and can retry.
- Streaming: the user sees each step instead of waiting for one big answer.
- Hessen DOP WMS (20 cm aerial imagery) loads directly in the map.
- Upload of GeoJSON/GPKG/zipped Shapefile/KML.

**Weak spots**
- **Overpass is the bottleneck**: 30–100 s per uncached query; whole-city
  queries are slow, and the public server regularly returns 502/504 (busy).
  osmnx retries 429/504 *forever* and sleeps 60 s per try on mirrors without a
  `/status` page. A real request hung > 10 min that way. `tools/osm.py` now
  wraps osmnx's request function with a 120 s deadline per server, skips the
  status check on mirrors and returns a clear "servers overloaded" error to the
  LLM. The first query of an area stays slow; repeats come from the cache.
- **Open-data search rarely yields loadable data**: CKAN returns datasets, but
  their resources are mostly websites/PDFs. The agent then has nothing to load.
- **`classify_surface` is fake**: the numbers come from a hash, not from imagery.
  Do not present them as results.
- **No persistence**: backend restart = sessions and layers gone.
- **Large layers**: all GeoJSON goes over SSE into the browser; 10k+ buildings
  get sluggish.
- **Map UI is minimal**: no layer toggle/removal, no feature popups, legend
  without colours; WMS tiles show nothing when zoomed far out (server scale limits).
- **Analysis gaps**: no attribute filter, difference/erase, spatial join,
  distance/nearest, dissolve-by-attribute, raster analysis, export/download.

## 11. Roadmap / TODO

Prioritised for the assignment:

**P1: needed to demo the goal convincingly**
- [x] LLM connected (Gemini free tier), first end-to-end runs work.
- [ ] Run all example prompts end-to-end; keep traces as evidence.
- [ ] Add analysis tools: `filter_by_attribute`, `difference`, `spatial_join` /
      `count_within`, `nearest_distance`, `dissolve` (by attribute).
- [ ] Make open data usable: filter CKAN results to vector formats
      (GeoJSON/WFS/GPKG/SHP) and/or add a small curated list of Hessen WFS
      endpoints (HVBG, HLNUG) to the system prompt.
- [ ] Download/export of a layer (GeoJSON/GPKG), so results leave the tool.
- [ ] Evaluation: a fixed set of ~10 prompts with expected tool sequences;
      run them and compare traces (cf. GeoAnalystBench).

**P2: quality**
- [ ] Real `classify_surface`: fetch DOP tiles for the AOI via WMS GetMap,
      run a segmentation model (torchgeo / HuggingFace, e.g. a land-cover
      SegFormer), return class shares + a polygon/raster layer.
- [ ] Layer panel: toggle visibility, delete, colour swatches, feature popups.
- [ ] Trim history (drop old tool summaries) to limit cost in long sessions.
- [ ] Exact pins: `requirements.lock`.

**P3: beyond the prototype**
- [ ] Persist sessions/layers (SQLite/PostGIS, GeoParquet files).
- [ ] Send large layers as files/vector tiles instead of inline GeoJSON.
- [ ] PyQGIS-backed tool set (Docker) for the full QGIS Processing registry.
- [ ] Multi-agent split (planner / executor / reviewer) as in GeoAgent.
- [ ] Auth, if it is ever hosted.

## 12. Research background (further reading)

- Li & Ning (2023), *Autonomous GIS: the next-generation AI-powered GIS*:
  LLM-Geo, the foundational solution-graph approach.
- *GIScience in the Era of AI: A Research Agenda Towards Autonomous GIS* (2025):
  taxonomy and open problems.
- *GIS Copilot: towards an autonomous GIS agent for spatial analysis* (2025):
  embedding an LLM into QGIS via documented tools (closest to this design).
- OpenGeoAgent / GeoAgent: open-source QGIS agent plugins (reference
  implementations).
- *Bridging natural language and GIS: a multi-agent framework* (2026):
  CoT + RAG over QGIS processing tools.
- *GeoAnalystBench* (2025): benchmark for evaluating LLM spatial workflows.
