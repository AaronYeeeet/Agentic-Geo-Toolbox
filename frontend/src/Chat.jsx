import { useRef, useState } from "react";
import { SessionLostError, streamChat, uploadFile } from "./api";

const SESSION_LOST_TEXT =
  "Das Backend wurde neu gestartet, die alte Session (und ihre Layer) ist weg. " +
  "Neue Session erstellt – bitte Nachricht erneut senden.";

export default function Chat({ sessionId, onLayer, onSessionLost }) {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const fileRef = useRef(null);

  const push = (msg) => setMessages((m) => [...m, msg]);

  async function send() {
    const text = input.trim();
    if (!text || busy || !sessionId) return;
    setInput("");
    push({ role: "user", text });
    setBusy(true);

    try {
      await streamChat(sessionId, text, (ev) => {
        if (ev.type === "tool_call") {
          push({ role: "status", text: `🛠️ ${ev.name}(${ev.arguments || ""})` });
        } else if (ev.type === "tool_result") {
          push({ role: "status", text: `↳ ${ev.summary}` });
        } else if (ev.type === "assistant_thought") {
          push({ role: "thought", text: ev.content });
        } else if (ev.type === "assistant_message") {
          push({ role: "assistant", text: ev.content });
        } else if (ev.type === "layer") {
          onLayer(ev.layer);
          push({ role: "status", text: `🗺️ added layer "${ev.layer.name}"` });
        } else if (ev.type === "error") {
          push({ role: "error", text: ev.message });
        }
      });
    } catch (e) {
      if (e instanceof SessionLostError) {
        push({ role: "error", text: SESSION_LOST_TEXT });
        onSessionLost();
      } else {
        push({ role: "error", text: String(e) });
      }
    } finally {
      setBusy(false);
    }
  }

  async function onFile(e) {
    const file = e.target.files?.[0];
    if (!file || !sessionId) return;
    push({ role: "status", text: `⬆️ uploading ${file.name}…` });
    try {
      const layer = await uploadFile(sessionId, file);
      onLayer(layer);
      push({ role: "status", text: `🗺️ loaded "${layer.name}" (${layer.feature_count} features)` });
    } catch (err) {
      if (err instanceof SessionLostError) {
        push({ role: "error", text: SESSION_LOST_TEXT });
        onSessionLost();
      } else {
        push({ role: "error", text: String(err) });
      }
    }
    e.target.value = "";
  }

  return (
    <div className="chat">
      <div className="messages">
        {messages.length === 0 && (
          <div className="hint">
            Ask about a place, e.g.:<br />
            <em>"Zeig mir alle Schulen in Darmstadt und einen 300 m Puffer darum."</em>
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`msg ${m.role}`}>{m.text}</div>
        ))}
        {busy && <div className="msg status">…thinking</div>}
      </div>

      <div className="composer">
        <button className="attach" onClick={() => fileRef.current?.click()} title="Upload geodata">＋</button>
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
    </div>
  );
}
