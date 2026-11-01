# Agentic Geo-Toolbox

Research prototype for an agentic geodata assistant (TU Darmstadt, Lab Visual Computing WiSe 2026/27, topic by
Fraunhofer IGD). A Google-Maps-like web map with a docked chat: select an area, ask a question, and the agent
answers with its steps, its sources and new layers on the map.

**Status: prototype.** Map shell, chat shell, source registry and agent protocol work end to end; the agent is a
scripted mock (`AGENT_MODE=mock`) that answers in English or German with clearly labelled demo data. An LLM agent
can replace it behind the same protocol.

## Features

- **Map** (MapLibre GL JS 6): starts at Fraunhofer IGD in Darmstadt, view in the URL hash, five basemaps (OSM by
  OpenFreeMap; basemap.de colour, grey and relief with OpenFreeMap fallbacks; aerial imagery composed from the open
  DOP WMS of 13 states plus a Sentinel-2 fallback), 2D/3D with Mapterhorn terrain, hillshade and 2.5D buildings.
- **Search** with Photon (debounced, German results first, results usable as the selection).
- **Selection tools**: rectangle, polygon, pick a building/place/result, current view; area chip in the composer.
- **Uploads** (GeoJSON, CSV with lat/lon detection incl. German Excel files, KML, GPX; max 10 MB) by paperclip or
  drag-and-drop; each becomes a layer, a context chip and clickable features.
- **Layer panel**: terrain, buildings, WMS overlays from the registry, uploads and agent results with toggle,
  opacity, legend, attribution, zoom-to and remove.
- **Chat**: streaming answers over SSE, tool steps, source chips, result actions, errors with retry, stop button,
  example prompts; resizable, collapsible, widenable dock on desktop and a bottom sheet on phones; EN/DE UI.
- **Backend** (FastAPI): `GET /api/health`, `GET /api/sources` (registry of 43 checked sources),
  `POST /api/chat` (server-sent events; models in `backend/app/protocol/models.py`).

## Setup

Prerequisites: git, make, [Node.js](https://nodejs.org/) (current LTS or newer) and
[uv](https://docs.astral.sh/uv/) (it installs Python 3.12 by itself). On macOS: `brew install node uv`.

```bash
git clone <repo-url> agentic-geo-toolbox
cd agentic-geo-toolbox
cp .env.example .env    # optional: the defaults work
make install            # uv sync + npm ci
make dev                # backend on :8000, frontend on :5173
```

Open <http://localhost:5173>. `Ctrl-C` stops both servers. No API keys or accounts are needed. Other ports:
`make dev BACKEND_PORT=8100 FRONTEND_PORT=5180`.

## Tests

| Command | What it runs |
|---|---|
| `make test` | backend pytest (133 tests: protocol, registry, language and intents, demo data, SSE chat), frontend typecheck and Vitest (108 tests) |
| `make lint` | ruff and oxlint |
| `make e2e-install` | downloads Chromium for Playwright (once) |
| `make e2e` | Playwright: smoke tests of the main features and an axe WCAG 2.1 AA audit; starts its own servers on :8001 and :5174 and fails on any console error |
| `make screenshots` | 20 screenshots (desktop and phone, EN and DE) into `frontend/screenshots/` plus a layout report |

Headless WebGL uses SwiftShader, so e2e runs work without a GPU (about a minute).

## Structure

```
backend/    FastAPI app: protocol models, SSE chat endpoint, mock agent, source registry (app/sources/registry.yaml)
frontend/   React + TypeScript + Vite + MapLibre: map, layers, search, selection, uploads, chat; e2e/ for Playwright
```

## Known limits

- The agent is a mock: its layers are generated demo data (labelled as such); only areas and the source list are
  real.
- basemap.de (BKG) was unreachable during testing; Official, Light and Relief currently show OpenFreeMap
  fallbacks with a notice.
- Aerial imagery covers 13 of 16 states (Sachsen-Anhalt and Schleswig-Holstein need HTTPS or a proxy; Hamburg is
  pending).

Map data © OpenStreetMap contributors and the other providers listed in `backend/app/sources/registry.yaml`; the map shows the
attribution of every active source.
