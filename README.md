# Geo-Agent

KI-Agent für Geofragen von Kommunen. Rechnet mit QGIS, statt Analysen selbst zu programmieren.
Code, Kommentare und Bezeichner sind auf Englisch.
Architektur: siehe Planungsdokument "Geo-Agent Neustart: Architektur mit QGIS-Workern".

| Ordner | Inhalt |
| --- | --- |
| `frontend/` | React + Vite + TypeScript; auf dem Server liefert Caddy die gebaute Seite aus |
| `backend/` | FastAPI; hier kommt der Agent hin |
| `qgis-worker/` | MCP-Server mit PyQGIS (QGIS 3.44 LTR im Docker-Image) |
| `litellm/` | `config.yaml`: welche LLMs der Proxy anbietet, mit Ausweichmodell |
| `db/init/` | SQL, das beim ersten Start der Datenbank läuft (legt die Datenbank `litellm` an) |
| `models/` | QGIS-Modelle (`.model3`), im Worker unter `/models` |
| `sources/` | Datenquellen als YAML |
| `data/` | Daten und Ergebnisse, nicht im Git, überall unter `/data` |

## Lokal starten

Voraussetzung: Docker Desktop (unter Windows mit WSL2).

```bash
cp .env.example .env
docker compose up --build
```

| Adresse | Was |
| --- | --- |
| http://localhost:5173 | Frontend, zeigt den Status aller Dienste |
| http://localhost:8000/api/health | Backend-Status als JSON |
| http://localhost:8000/docs | API-Dokumentation |
| http://localhost:8000/api/llm-ping | Schickt einen kurzen Prompt durch LiteLLM an das Modell |
| http://localhost:8100/health | QGIS-Worker: Version und Anzahl Algorithmen |
| http://localhost:4000/health/liveliness | LiteLLM-Proxy läuft |
| http://localhost:8100/mcp | MCP-Endpunkt, z. B. für `npx @modelcontextprotocol/inspector` |
| localhost:5432 | PostGIS, Zugang aus `.env`, z. B. aus QGIS Desktop |

Die Datenbank hat zwei Teile: `geo` für unsere Geodaten und `litellm` für LiteLLM (Schlüssel, Budgets, Kosten).
`db/init/` läuft nur, wenn das Datenbank-Volume neu angelegt wird. Bei einem älteren Volume ohne `litellm` einmal:

```bash
docker compose exec db createdb -U geo litellm
```

Für den LLM-Test in `.env` einen eigenen `OPENROUTER_API_KEY` eintragen (kostenlos auf openrouter.ai).
Modelle ändern: `litellm/config.yaml` bearbeiten, dann `docker compose restart litellm`.

Code in `frontend/src`, `backend/app` und `qgis-worker/server.py` wird eingebunden:
Frontend und Backend laden Änderungen selbst neu, den Worker nach Änderungen neu starten:

```bash
docker compose restart qgis
```

Neue Abhängigkeit (package.json, pyproject.toml, requirements.txt) = neu bauen: `docker compose up --build`.

## Auf dem Server

Linux-Server mit Docker. Die Domain muss auf den Server zeigen, Ports 80 und 443 offen.

```bash
git clone <repo> && cd geo-agent
cp .env.example .env   # starke Passwörter, DOMAIN=<eure Domain>
docker compose -f docker-compose.yml -f compose.prod.yml up -d --build
```

Caddy holt das HTTPS-Zertifikat selbst. Nur 80 und 443 sind offen; Datenbank, Backend und Worker sind von außen nicht erreichbar.

Update: `git pull`, dann denselben `docker compose ... up -d --build`-Befehl.

## Als Nächstes

- Agent mit Pydantic AI und LiteLLM im Backend
- Werkzeugkatalog aus `qgis_process help --json` im Worker
- Speicherschicht (PostGIS) und Arbeitsbereich je Frage
- Chat und Karte (MapLibre) im Frontend
