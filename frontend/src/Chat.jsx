import { useEffect, useRef, useState } from "react";
import Turn from "./Turn.jsx";
import { getHistory } from "./api";

// The full LLM context of a chat (system prompt, all messages, tool results).
function ContextModal({ sessionId, onClose }) {
  const [history, setHistory] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => { getHistory(sessionId).then(setHistory).catch((e) => setError(String(e))); }, [sessionId]);

  return (
    <div className="modal-bg" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="settings-head">
          <strong>Kompletter LLM-Kontext {history && `(${history.length} Nachrichten)`}</strong>
          <button className="link" onClick={onClose}>schließen</button>
        </div>
        <p className="settings-note">
          Das bekommt das Modell bei der nächsten Anfrage. Geometrien sind nie enthalten,
          nur Layer-IDs und Zusammenfassungen.
        </p>
        {error && <div className="msg error">{error}</div>}
        {!history && !error && <div className="step-meta">lädt…</div>}
        {history?.length === 0 && <div className="step-meta">Noch leer.</div>}
        {history?.map((m, i) => (
          <div key={i} className={`ctx-msg ${m.role}`}>
            <span className="role">#{i} {m.role}{m.tool_call_id ? ` · ${m.tool_call_id}` : ""}</span>
            {m.content && <pre className="clip">{m.content}</pre>}
            {(m.tool_calls || []).map((tc) => (
              <pre key={tc.id} className="clip">→ {tc.function.name}({tc.function.arguments})</pre>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

export default function Chat({ sessionId, turns, busy, debug, onSend, onUpload }) {
  const [input, setInput] = useState("");
  const [showContext, setShowContext] = useState(false);
  const fileRef = useRef(null);
  const endRef = useRef(null);

  // Keep the newest event in view.
  useEffect(() => { endRef.current?.scrollIntoView({ block: "end" }); }, [turns]);

  function send() {
    const text = input.trim();
    if (!text || busy || !sessionId) return;
    setInput("");
    onSend(text);
  }

  function onFile(e) {
    const file = e.target.files?.[0];
    if (file && sessionId) onUpload(file);
    e.target.value = "";
  }

  return (
    <div className="chat">
      <div className="messages">
        {turns.length === 0 && (
          <div className="hint">
            Frag nach einem Ort, z.&nbsp;B.:<br />
            <em>„Zeig mir alle Schulen in Darmstadt und einen 300 m Puffer darum.“</em>
            <br /><br />
            Über <strong>Details</strong> oben siehst du zusätzlich jeden LLM-Aufruf mit Ein- und Ausgabe.
          </div>
        )}
        {turns.map((t) => <Turn key={t.key} events={t.events} running={t.running} debug={debug} />)}
        {debug && turns.length > 0 && (
          <button className="link ctx-open" onClick={() => setShowContext(true)}>
            📜 Kompletten LLM-Kontext anzeigen
          </button>
        )}
        <div ref={endRef} />
      </div>

      <div className="composer">
        <button className="attach" onClick={() => fileRef.current?.click()} title="Geodaten hochladen" disabled={busy}>＋</button>
        <input ref={fileRef} type="file" hidden onChange={onFile}
          accept=".geojson,.json,.gpkg,.zip,.kml,.gml" />
        <textarea
          value={input}
          placeholder="Nachricht an den Geo-Agenten…"
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
        />
        <button className="send" onClick={send} disabled={busy}>Senden</button>
      </div>
      {showContext && <ContextModal sessionId={sessionId} onClose={() => setShowContext(false)} />}
    </div>
  );
}
