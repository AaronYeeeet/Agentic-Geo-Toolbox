import { useEffect, useState } from "react";
import MapView from "./MapView.jsx";
import Chat from "./Chat.jsx";
import { createSession, getHealth } from "./api";

export default function App() {
  const [sessionId, setSessionId] = useState(null);
  const [layers, setLayers] = useState([]);
  const [health, setHealth] = useState(null);
  const [backendDown, setBackendDown] = useState(false);

  const newSession = () =>
    createSession()
      .then((id) => { setSessionId(id); setBackendDown(false); return id; })
      .catch((e) => { console.error(e); setBackendDown(true); return null; });

  useEffect(() => {
    newSession();
    getHealth().then(setHealth).catch(() => setBackendDown(true));
  }, []);

  const addLayer = (layer) =>
    setLayers((prev) => (prev.some((l) => l.id === layer.id) ? prev : [...prev, layer]));

  return (
    <div className="app">
      <div className="sidebar">
        <header className="brand">
          <h1>🌍 Agentic Geo Toolbox</h1>
          <span className="session">
            {sessionId ? sessionId : "connecting…"}
            {health && ` · ${health.model}`}
          </span>
        </header>
        {backendDown && (
          <div className="banner error">
            Backend nicht erreichbar. Läuft <code>uvicorn app.main:app --port 8000</code>?
          </div>
        )}
        {health && !health.llm_configured && (
          <div className="banner">
            Kein API-Key für <code>{health.model}</code> gesetzt
            ({health.llm_missing_keys.join(" oder ")}): Uploads und Karte funktionieren,
            der Agent antwortet aber nicht. Siehe <code>backend/.env</code>.
          </div>
        )}
        <Chat sessionId={sessionId} onLayer={addLayer} onSessionLost={newSession} />
      </div>
      <div className="map-wrap">
        <MapView layers={layers} />
        {layers.length > 0 && (
          <div className="legend">
            <strong>Layers</strong>
            {layers.map((l) => (
              <div key={l.id} className="legend-item">{l.name}</div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
