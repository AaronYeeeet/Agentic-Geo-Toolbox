import { useEffect, useRef, useState } from "react";
import MapView from "./MapView.jsx";
import Chat from "./Chat.jsx";
import SessionList from "./SessionList.jsx";
import LayerPanel from "./LayerPanel.jsx";
import Settings, { loadSettings, saveSettings } from "./Settings.jsx";
import {
  SessionLostError, createSession, deleteLayer, deleteSession, getHealth, getModels,
  getLayerGeojson, getSession, listSessions, renameSession, streamChat, updateLayer, uploadFile,
} from "./api";

// Per-browser conveniences; storage may be unavailable (private mode).
const store = {
  get: (k, d) => { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; } },
  set: (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* ignore */ } },
};

let turnKey = 0;
const asTurn = (events, running = false) => ({ key: ++turnKey, events, running });

export default function App() {
  const [health, setHealth] = useState(null);
  const [backendDown, setBackendDown] = useState(false);
  const [models, setModels] = useState([]);
  const [settings, setSettings] = useState(loadSettings);
  const [showSettings, setShowSettings] = useState(false);
  const [debug, setDebug] = useState(() => store.get("geo-toolbox-debug", false));
  const [railOpen, setRailOpen] = useState(() => store.get("geo-toolbox-rail", true));

  const [sessions, setSessions] = useState([]);
  const [sessionId, setSessionId] = useState(null);
  const [title, setTitle] = useState("Neuer Chat");
  const [turns, setTurns] = useState([]);
  const [layers, setLayers] = useState([]);
  const [focus, setFocus] = useState(null);
  const [busy, setBusy] = useState(false);
  const sessionRef = useRef(null);
  sessionRef.current = sessionId;

  const changeSettings = (next) => { setSettings(next); saveSettings(next); };
  const toggleDebug = () => { setDebug(!debug); store.set("geo-toolbox-debug", !debug); };
  const toggleRail = () => { setRailOpen(!railOpen); store.set("geo-toolbox-rail", !railOpen); };
  const refreshModels = () => getModels().then(setModels).catch(console.error);
  const refreshSessions = () => listSessions().then(setSessions).catch(console.error);
  const zoomTo = (ids) => setFocus({ ids, nonce: Date.now() });

  // ---- chats ----------------------------------------------------------------

  async function newChat() {
    try {
      const id = await createSession();
      setSessionId(id); setTitle("Neuer Chat"); setTurns([]); setLayers([]);
      store.set("geo-toolbox-last-session", id);
      setBackendDown(false);
    } catch (e) {
      console.error(e); setBackendDown(true);
    }
  }

  async function openChat(id) {
    try {
      const data = await getSession(id);
      setSessionId(id); setTitle(data.title);
      setTurns(data.turns.map((events) => asTurn(events)));
      setLayers(data.layers);
      zoomTo(data.layers.filter((l) => l.visible !== false).map((l) => l.id));
      store.set("geo-toolbox-last-session", id);
    } catch (e) {
      if (e instanceof SessionLostError) { refreshSessions(); newChat(); }
      else { console.error(e); setBackendDown(true); }
    }
  }

  async function removeChat(id) {
    await deleteSession(id).catch(console.error);
    await refreshSessions();
    if (id === sessionId) newChat();
  }

  async function rename(id, newTitle) {
    await renameSession(id, newTitle).catch(console.error);
    if (id === sessionId) setTitle(newTitle);
    refreshSessions();
  }

  useEffect(() => {
    getHealth().then(setHealth).catch(() => setBackendDown(true));
    refreshModels();
    refreshSessions();
    const last = store.get("geo-toolbox-last-session", null);
    if (last) openChat(last); else newChat();
  }, []);

  // A remembered model may have left the catalog (OpenRouter's free list changes).
  useEffect(() => {
    if (models.length && settings.model && !models.some((m) => m.id === settings.model)) {
      changeSettings({ ...settings, model: null });
    }
  }, [models]);

  // ---- layers ---------------------------------------------------------------

  // Descriptors carry only metadata; fetch the GeoJSON of every visible layer
  // that doesn't have it yet (hidden ones load when they are switched on).
  const loadingRef = useRef(new Set());
  useEffect(() => {
    const sid = sessionId;
    for (const l of layers) {
      if (l.kind !== "geojson" || l.geojson || l.visible === false || l.loadError) continue;
      const key = `${sid}/${l.id}`;
      if (loadingRef.current.has(key)) continue;
      loadingRef.current.add(key);
      getLayerGeojson(sid, l.id)
        .then((geojson) => ({ geojson }))
        .catch((e) => ({ loadError: String(e) }))
        .then((patch) => {
          loadingRef.current.delete(key);
          if (sessionRef.current !== sid) return;
          setLayers((prev) => prev.map((x) => (x.id === l.id ? { ...x, ...patch } : x)));
        });
    }
  }, [layers, sessionId]);

  const upsertLayer = (layer) => {
    setLayers((prev) => {
      const i = prev.findIndex((l) => l.id === layer.id);
      if (i === -1) return [...prev, layer];
      const next = [...prev];
      next[i] = { ...prev[i], ...layer, visible: true };
      return next;
    });
    if (layer.bounds) zoomTo([layer.id]);
  };

  const toggleLayer = (id, visible) => {
    setLayers((prev) => prev.map((l) => (l.id === id ? { ...l, visible } : l)));
    updateLayer(sessionId, id, { visible }).catch(console.error);
  };

  const removeLayer = (id) => {
    setLayers((prev) => prev.filter((l) => l.id !== id));
    deleteLayer(sessionId, id).catch(console.error);
  };

  // ---- sending --------------------------------------------------------------

  // Append to the last (running) turn.
  const pushEvent = (ev) => setTurns((prev) => {
    const last = prev[prev.length - 1];
    const events = ev.type === "user"
      ? [ev, ...last.events.filter((e) => e.type !== "user")] // server echo replaces the local one
      : [...last.events, ev];
    return [...prev.slice(0, -1), { ...last, events }];
  });

  async function send(text) {
    const sid = sessionId;
    setBusy(true);
    setTurns((prev) => [...prev, asTurn([{ type: "user", content: text }], true)]);
    try {
      await streamChat(sid, text, settings, (ev) => {
        if (sessionRef.current !== sid) return;
        if (ev.type === "layer") upsertLayer(ev.layer);
        pushEvent(ev);
      });
    } catch (e) {
      pushEvent({
        type: "error",
        message: e instanceof SessionLostError
          ? "Dieser Chat existiert im Backend nicht mehr. Starte einen neuen Chat."
          : String(e),
      });
    } finally {
      setTurns((prev) => prev.map((t) => ({ ...t, running: false })));
      setBusy(false);
      listSessions().then((list) => {
        setSessions(list);
        const me = list.find((s) => s.id === sid);
        if (me && sessionRef.current === sid) setTitle(me.title);
      }).catch(() => {});
    }
  }

  async function upload(file) {
    try {
      const layer = await uploadFile(sessionId, file);
      upsertLayer(layer);
      setTurns((prev) => [...prev, asTurn([{ type: "upload", filename: file.name, feature_count: layer.feature_count }])]);
      refreshSessions();
    } catch (e) {
      setTurns((prev) => [...prev, asTurn([{ type: "error", message: String(e) }])]);
    }
  }

  // ---- render ---------------------------------------------------------------

  const activeModel = settings.model || health?.model;
  const activeInfo = models.find((m) => m.id === activeModel);
  const missingKeys = activeInfo ? activeInfo.missing_keys : health?.llm_missing_keys || [];

  return (
    <div className="app">
      {railOpen && (
        <SessionList sessions={sessions} activeId={sessionId} busy={busy}
          onOpen={openChat} onNew={newChat} onRename={rename} onDelete={removeChat} />
      )}
      <div className="sidebar">
        <header className="brand">
          <div className="brand-row">
            <button className="gear" title={railOpen ? "Chatliste ausblenden" : "Chatliste einblenden"}
              onClick={toggleRail}>☰</button>
            <h1 title={title}>{title}</h1>
            <label className="toggle" title="LLM-Ein- und Ausgaben anzeigen">
              <input type="checkbox" checked={debug} onChange={toggleDebug} />
              <span>Details</span>
            </label>
            <button className="gear" title="Einstellungen"
              onClick={() => { setShowSettings(!showSettings); if (!showSettings) refreshModels(); }}>⚙️</button>
          </div>
          <span className="session">
            🌍 Agentic Geo Toolbox · {activeInfo?.name || activeModel || "…"}
            {debug && sessionId && ` · ${sessionId}`}
          </span>
        </header>
        {showSettings && (
          <Settings models={models} settings={settings} health={health}
            onChange={changeSettings} onClose={() => setShowSettings(false)} />
        )}
        {backendDown && (
          <div className="banner error">
            Backend nicht erreichbar. Läuft <code>uvicorn app.main:app --port 8000</code>?
          </div>
        )}
        {health && missingKeys.length > 0 && (
          <div className="banner">
            Kein API-Key für <code>{activeModel}</code> gesetzt
            ({missingKeys.join(" oder ")}): Uploads und Karte funktionieren,
            der Agent antwortet aber nicht. Key in <code>backend/.env</code> eintragen
            oder in ⚙️ ein anderes Modell wählen.
          </div>
        )}
        <Chat sessionId={sessionId} turns={turns} busy={busy} debug={debug}
          onSend={send} onUpload={upload} />
      </div>
      <div className="map-wrap">
        <MapView layers={layers} focus={focus} />
        <LayerPanel layers={layers} onToggle={toggleLayer} onZoom={(id) => zoomTo([id])}
          onDelete={removeLayer} />
      </div>
    </div>
  );
}
