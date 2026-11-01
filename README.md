# 🌍 Agentic Geo Toolbox

A chat-based agentic system for geospatial analysis. The user uploads custom
data and writes natural-language prompts in a chat UI next to an interactive
map. An LLM figures out which **tools** to call to fulfil the task — pulling
from public data providers (OpenStreetMap, WMS, Open Data Hessen) and running
processing tools (GeoPandas geoprocessing, an AI surface-classification model) —
and streams the resulting map layers back to the browser.

This project accompanies a university assignment and is built to be
**reproducible**: every agent run is logged as a JSON trace.

---

## Architecture

```
React + Vite + MapLibre GL          FastAPI (Python)
┌───────────────────────┐  SSE /   ┌──────────────────────────────┐
│ Chat panel  +  Map     │ HTTP     │ Agent orchestrator (LLM loop) │
│  - prompts, uploads    │◄────────►│  - LiteLLM (Claude | Ollama)  │
│  - renders layers      │          │  - tool registry + schemas    │
└───────────────────────┘          └───────────────┬──────────────┘
                                                    │ tool calls
                   ┌────────────────────────────────┼────────────────────────┐
                   ▼                                 ▼                        ▼
         Data tools                        Processing tools          AI model
   OSM (osmnx) · WMS (owslib)       GeoPandas/Shapely/GDAL       surface classifier
   Open Data Hessen (CKAN)          buffer·clip·overlay·stats     (stub interface)
```

The agent never generates free-form code; it selects from **declared tools**
with JSON schemas (Claude/LiteLLM function calling). This keeps runs safe,
inspectable and reproducible. See [`docs/architecture.md`](docs/architecture.md)
for the full design and the research background.

## Tech decisions

| Layer        | Choice                                   |
|--------------|------------------------------------------|
| Frontend     | React + Vite + MapLibre GL               |
| Backend      | FastAPI, streaming via Server-Sent Events |
| LLM          | Provider-abstracted via **LiteLLM** (Claude *or* local Ollama) |
| Geoprocessing| GeoPandas / Shapely / GDAL               |
| Surface classification | Stub with a stable tool interface (swap in a real model later) |
| OSM access   | osmnx → Overpass API, cached on disk     |

---

## Quick start

### 1. Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# edit .env: set ANTHROPIC_API_KEY (Claude) OR point LLM_MODEL/LLM_API_BASE at Ollama

python -m scripts.smoke_test --offline   # optional: check the tools work (no LLM needed)
uvicorn app.main:app --reload --port 8000
```

Check `http://localhost:8000/api/health`. It lists the active model, the tools,
and `llm_configured` (false = no API key, the agent won't answer).

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`.

### 3. Try it

- *"Zeig mir alle Schulen in Darmstadt und einen 300 m Puffer darum."*
- *"Lade alle Parks in Wiesbaden und zeig mir ihre Gesamtfläche."*
- *"Zeig mir das Luftbild von Hessen über der Karte."* (Hessen DOP WMS)
- Upload a GeoJSON/GeoPackage with the ＋ button, then ask the agent to buffer
  or clip it.

The first OSM query for a city takes 30–100 s (Overpass API); repeats come from
the cache in `backend/workspace/osm_cache/`.

### Testing without an LLM

`python -m scripts.smoke_test` (from `backend/`) calls every tool directly and
prints ok/FAIL plus timing, with no API key needed. `--offline` skips all
network services. Use it to tell tool bugs from LLM planning mistakes.

---

## Switching the LLM provider

Everything routes through `backend/app/agent/llm.py` (LiteLLM). Change only
`.env`:

```ini
# Claude (cloud), API key from https://console.anthropic.com
LLM_MODEL=anthropic/claude-opus-5-5        # or claude-sonnet-5-5 / claude-haiku-5-5 (cheaper)
ANTHROPIC_API_KEY=sk-ant-...

# Google Gemini (free tier, key from https://aistudio.google.com/apikey)
LLM_MODEL=gemini/gemini-3.5-flash
GEMINI_API_KEY=...

# Groq (free tier, key from https://console.groq.com/keys)
LLM_MODEL=groq/openai/gpt-oss-120b
GROQ_API_KEY=...

# Local (Ollama, free, offline): install from https://ollama.com, then `ollama pull qwen3:8b`
LLM_MODEL=ollama_chat/qwen3:8b
LLM_API_BASE=http://localhost:11434
```

Every line of `.env` is exported to the environment, so any provider LiteLLM
supports works by setting its key variable. `/api/health` reports
`llm_missing_keys` if the key for `LLM_MODEL` is missing. Free cloud tiers have
tight request limits (Gemini free tier: 5 requests/minute **and only 20
requests/day** per model), and one agent turn uses one request per step (often
3–10), so the daily quota lasts only a few turns. On HTTP 429 the backend waits
as long as the provider asks and retries (`agent/llm.py`), so a turn may pause
for a few seconds instead of failing. A used-up daily quota fails immediately
with a clear message; switch `LLM_MODEL` (e.g. to Groq) to keep testing.
Tested Nov 2026: `gemini-3.5-flash` works
well; `gemini-2.5-flash` is no longer available to new keys; `gemini-3.8-flash`
did not respond within 60 s.

Small local models plan noticeably worse (wrong tools, invented layer ids).
They are fine for testing the plumbing, not for judging the agent.

## Reproducibility

Each user turn writes a full event trace (plan → tool calls → arguments →
results) to `backend/workspace/<session_id>/traces/`. Uploaded files are kept
under the same session folder. Pin dependencies via `requirements.txt` /
`package-lock.json` to reproduce an environment.

## Troubleshooting

| Symptom | Cause / fix |
|---------|-------------|
| Chat shows `No module named 'mcp'` | LiteLLM ≥ 1.106 needs it: `pip install -r requirements.txt` |
| `AuthenticationError` / banner "Kein API-Key" | set `ANTHROPIC_API_KEY` in `backend/.env`, restart uvicorn |
| "Backend wurde neu gestartet …" | sessions live in memory; `--reload` restarts on every code change. Resend the message. |
| `fetch_osm` takes minutes or `502 Bad Gateway` | Overpass is overloaded; mirrors are tried automatically, retry later or use a smaller bbox |
| Where is my request? | `backend/workspace/<session>/traces/`, written live after every step; the session id is shown under the title in the UI |
| Map grey, "Karte nicht verfügbar" | WebGL disabled in the browser (`chrome://gpu`) |
| WMS overlay empty | many WMS only render at closer zoom levels: zoom in |

## Adding a tool

1. Create a function in `backend/app/agent/tools/` decorated with `@tool(name,
   description, parameters)` returning a `ToolResult`.
2. Import it in `tools/__init__.py`.

That's it: the agent discovers it automatically via the registry. Write the
`description` for the LLM. It is the only documentation the model sees, so say
when to use the tool and what it returns. Raise exceptions with helpful
messages; they are passed back to the LLM so it can correct itself.

## Project status

Working prototype. What works, what doesn't and the TODO list are in
[`docs/architecture.md` §10–11](docs/architecture.md#10-what-works-well--what-doesnt).
