# Agentic Geo-Toolbox

Research prototype (TU Darmstadt, Fraunhofer IGD): a map plus a chat assistant whose agent finds geodata, runs tools
and puts every result on the map as a toggleable layer.

- `frontend/`: React 19, TypeScript (strict), Vite 8, MapLibre GL JS 6, Terra Draw, Zustand, Tailwind 4 +
  shadcn/ui (Radix), react-i18next.
- `backend/`: FastAPI on Python 3.12 via uv. `/api/health`, `/api/sources`, `/api/chat` (SSE). The agent is a
  scripted mock (`AGENT_MODE=mock`).

## Commands

`make install`, `make dev` (backend :8000, frontend :5173 proxying `/api`), `make test` (pytest, tsc, vitest),
`make lint`, `make e2e`, `make screenshots`. Single tests: `cd backend && uv run pytest -k <name>`,
`cd frontend && npx vitest run <path>`.

## Conventions

- The SSE protocol is the contract between backend and frontend: change `backend/app/protocol/models.py` and
  `frontend/src/api/protocol.ts` together.
- UI text comes only from i18n keys in `frontend/src/i18n/{en,de}.json`; both files keep identical keys (a test
  checks).
- Map state lives in the Zustand stores; `frontend/src/map/overlays.ts` reconciles them onto the map after every
  style load, so add layers through the stores.
- Map code follows MapLibre v6 (named imports, `setWorkerUrl` in `main.tsx`, public camera API).
- A new data source is a verified entry (reachable, CORS, EPSG:3857 for WMS, license, exact attribution) in
  `backend/app/sources/registry.yaml`. Free and keyless sources only.
- Good citizen: Photon debounced (3+ characters), Nominatim only server-side at 1 req/s, attributions visible.
- Conventional commits.
