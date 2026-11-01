// Left rail: saved chats (newest first), new chat, rename, delete.
import { useState } from "react";

function when(ts) {
  const d = new Date(ts * 1000);
  const now = new Date();
  const days = Math.floor((new Date(now.toDateString()) - new Date(d.toDateString())) / 864e5);
  const time = d.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" });
  if (days === 0) return `heute ${time}`;
  if (days === 1) return `gestern ${time}`;
  return d.toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit", year: "2-digit" });
}

export default function SessionList({ sessions, activeId, busy, onOpen, onNew, onRename, onDelete }) {
  const [editing, setEditing] = useState(null);
  const [draft, setDraft] = useState("");
  // A new chat is only saved after its first message; show it anyway.
  const items = sessions.some((s) => s.id === activeId) || !activeId
    ? sessions
    : [{ id: activeId, title: "Neuer Chat", updated: Date.now() / 1000, unsaved: true }, ...sessions];

  const commit = (id) => {
    if (draft.trim()) onRename(id, draft.trim());
    setEditing(null);
  };

  return (
    <nav className="rail">
      <button className="new-chat" onClick={onNew} disabled={busy}>＋ Neuer Chat</button>
      <div className="rail-list">
        {items.length === 0 && <div className="rail-empty">Noch keine Chats.</div>}
        {items.map((s) => (
          <div key={s.id}
            className={`rail-item${s.id === activeId ? " active" : ""}${busy && s.id !== activeId ? " locked" : ""}`}
            title={busy && s.id !== activeId ? "Während der Agent arbeitet nicht wechselbar" : s.title}
            onClick={() => !busy && s.id !== activeId && editing !== s.id && onOpen(s.id)}>
            {editing === s.id ? (
              <input autoFocus value={draft} onChange={(e) => setDraft(e.target.value)}
                onClick={(e) => e.stopPropagation()}
                onBlur={() => commit(s.id)}
                onKeyDown={(e) => { if (e.key === "Enter") commit(s.id); if (e.key === "Escape") setEditing(null); }} />
            ) : (
              <>
                <div className="rail-title">{s.title}</div>
                <div className="rail-meta">{s.unsaved ? "noch leer" : when(s.updated)}</div>
                {!s.unsaved && (
                  <div className="rail-actions">
                    <button title="Umbenennen" onClick={(e) => {
                      e.stopPropagation(); setDraft(s.title); setEditing(s.id);
                    }}>✎</button>
                    <button title="Löschen" disabled={busy && s.id === activeId} onClick={(e) => {
                      e.stopPropagation();
                      if (confirm(`Chat „${s.title}“ mit allen Layern löschen?`)) onDelete(s.id);
                    }}>🗑</button>
                  </div>
                )}
              </>
            )}
          </div>
        ))}
      </div>
    </nav>
  );
}
