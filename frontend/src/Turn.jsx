// One user turn: prompt, a collapsible "what the agent did" block, the answer.
// The block lists thoughts and tool calls (arguments, result, duration); in
// detail mode it also shows every LLM call with its input and output.
import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";

const LONG = 600; // characters before text is cut with "mehr anzeigen"

function fmtS(s) {
  return s == null ? "" : `${s.toFixed(1).replace(".", ",")} s`;
}

function Clip({ text, className = "" }) {
  const [full, setFull] = useState(false);
  const s = String(text ?? "");
  if (s.length <= LONG || full) return <pre className={`clip ${className}`}>{s}</pre>;
  return (
    <pre className={`clip ${className}`}>
      {s.slice(0, LONG)}…{" "}
      <button className="link" onClick={() => setFull(true)}>mehr anzeigen ({s.length} Zeichen)</button>
    </pre>
  );
}

function prettyArgs(raw) {
  try {
    const obj = typeof raw === "string" ? JSON.parse(raw || "{}") : raw;
    return Object.entries(obj || {});
  } catch {
    return [["(roh)", raw]];
  }
}

function Args({ raw }) {
  const entries = prettyArgs(raw);
  if (!entries.length) return null;
  return (
    <dl className="args">
      {entries.map(([k, v]) => (
        <div key={k}><dt>{k}</dt><dd>{typeof v === "string" ? v : JSON.stringify(v)}</dd></div>
      ))}
    </dl>
  );
}

// Group the flat event list into display items.
function buildItems(events) {
  const items = [];
  let tool = null;
  for (const ev of events) {
    if (ev.type === "llm_request") items.push({ kind: "llm", req: ev, res: null });
    else if (ev.type === "llm_response") {
      const open = [...items].reverse().find((i) => i.kind === "llm" && !i.res);
      if (open) open.res = ev; else items.push({ kind: "llm", req: null, res: ev });
    } else if (ev.type === "assistant_thought") items.push({ kind: "thought", text: ev.content });
    else if (ev.type === "tool_call") {
      tool = { kind: "tool", call: ev, layers: [], result: null };
      items.push(tool);
    } else if (ev.type === "layer" && tool) tool.layers.push(ev.layer);
    else if (ev.type === "tool_result" && tool) { tool.result = ev; tool = null; }
  }
  return items;
}

function ToolItem({ item, running }) {
  const { call, result, layers } = item;
  const dur = result && call.t != null && result.t != null ? result.t - call.t : null;
  const failed = result?.summary?.startsWith("ERROR");
  return (
    <div className={`step tool${failed ? " failed" : ""}`}>
      <div className="step-head">
        <span>🛠️ <strong>{call.name}</strong></span>
        <span className="step-meta">{result ? fmtS(dur) : running ? <span className="spinner" /> : "abgebrochen"}</span>
      </div>
      <Args raw={call.arguments} />
      {result && <Clip text={result.summary} className="result" />}
      {layers.map((l) => <span key={l.id} className="chip">🗺️ {l.name}</span>)}
    </div>
  );
}

function Message({ m }) {
  return (
    <div className={`ctx-msg ${m.role}`}>
      <span className="role">{m.role}{m.tool_call_id ? ` · ${m.tool_call_id}` : ""}</span>
      {m.content ? <Clip text={m.content} /> : null}
      {(m.tool_calls || []).map((tc) => (
        <Clip key={tc.id} text={`→ ${tc.function.name}(${tc.function.arguments})`} />
      ))}
    </div>
  );
}

function LlmItem({ item, running }) {
  const { req, res } = item;
  const step = req?.step ?? res?.step;
  const usage = res?.usage;
  return (
    <div className="step llm">
      <div className="step-head">
        <span>🧠 <strong>LLM-Aufruf #{step}</strong> <span className="step-meta">{req?.model}</span></span>
        <span className="step-meta">
          {res ? fmtS(res.duration_s) : running ? <span className="spinner" /> : "keine Antwort"}
          {usage?.prompt_tokens != null && ` · ${usage.prompt_tokens} → ${usage.completion_tokens} Tokens`}
        </span>
      </div>
      {req && (
        <details>
          <summary>
            Eingabe: {req.new_messages.length} neue von {req.total_messages} Nachrichten,
            {" "}{req.tools.length} Tools{req.temperature != null ? `, Temperatur ${req.temperature}` : ""}
          </summary>
          {req.new_messages.map((m, i) => <Message key={i} m={m} />)}
          <div className="ctx-tools">Tools: {req.tools.join(", ")}</div>
        </details>
      )}
      {res && (
        <details>
          <summary>
            Ausgabe: {res.tool_calls.length ? `${res.tool_calls.length} Tool-Aufruf(e)` : "Antworttext"}
            {res.finish_reason ? ` · ${res.finish_reason}` : ""}
          </summary>
          {res.reasoning && (<><div className="ctx-label">Reasoning</div><Clip text={res.reasoning} className="reasoning" /></>)}
          {res.content && (<><div className="ctx-label">Text</div><Clip text={res.content} /></>)}
          {res.tool_calls.map((tc, i) => <Clip key={i} text={`→ ${tc.name}(${tc.arguments})`} />)}
        </details>
      )}
    </div>
  );
}

export default function Turn({ events, running, debug }) {
  const user = events.find((e) => e.type === "user");
  const upload = events.find((e) => e.type === "upload");
  const answer = events.find((e) => e.type === "assistant_message");
  const error = events.find((e) => e.type === "error");
  const aborted = events.some((e) => e.type === "aborted");
  const items = buildItems(events).filter((i) => debug || i.kind !== "llm");
  const tools = items.filter((i) => i.kind === "tool");
  const duration = [...events].reverse().find((e) => e.t != null)?.t;

  // Open while the agent works, collapse once it is done (ChatGPT-style);
  // in detail mode it stays open.
  const [open, setOpen] = useState(running || debug);
  useEffect(() => { setOpen(running || debug); }, [running, debug]);

  if (upload) {
    return <div className="msg status">📎 {upload.filename} hochgeladen ({upload.feature_count} Features)</div>;
  }

  const current = running && [...items].reverse().find((i) => i.kind === "tool");
  const summary = running
    ? `Arbeitet…${current ? ` ${current.call.name}` : ""}`
    : `${tools.length} ${tools.length === 1 ? "Werkzeug" : "Werkzeuge"}${duration != null ? ` · ${fmtS(duration)}` : ""}`;

  return (
    <div className="turn">
      {user && <div className="msg user">{user.content}</div>}
      {(items.length > 0 || running) && (
        <div className={`activity${open ? " open" : ""}`}>
          <button className="activity-head" onClick={() => setOpen(!open)}>
            <span>{running && <span className="spinner" />} {summary}</span>
            <span className="step-meta">
              {debug && user?.model ? `${user.model} · ` : ""}{open ? "▾" : "▸"}
            </span>
          </button>
          {open && (
            <div className="activity-body">
              {items.map((item, i) =>
                item.kind === "tool" ? <ToolItem key={i} item={item} running={running} />
                  : item.kind === "llm" ? <LlmItem key={i} item={item} running={running} />
                    : <div key={i} className="step thought">💭 {item.text}</div>)}
              {running && items.length === 0 && <div className="step-meta">Warte auf das Modell…</div>}
            </div>
          )}
        </div>
      )}
      {answer && <div className="msg assistant"><ReactMarkdown>{answer.content}</ReactMarkdown></div>}
      {error && <div className="msg error">{error.message}</div>}
      {aborted && <div className="msg error">Abgebrochen (Seite neu geladen oder Verbindung getrennt).</div>}
      {!running && !answer && !error && !aborted && user && (
        <div className="msg status">Keine Antwort gespeichert (Lauf wurde unterbrochen).</div>
      )}
    </div>
  );
}
