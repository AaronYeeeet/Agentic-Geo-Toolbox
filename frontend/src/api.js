// Thin client for the backend API. All requests go through the Vite proxy (/api).

// Sessions live in backend memory, so a backend restart (e.g. uvicorn --reload)
// invalidates the frontend's session_id. Callers catch this and create a new one.
export class SessionLostError extends Error {}

export async function getHealth() {
  const res = await fetch("/api/health");
  if (!res.ok) throw new Error("Backend not reachable");
  return res.json();
}

export async function getModels() {
  const res = await fetch("/api/models");
  if (!res.ok) throw new Error("Could not load models");
  return (await res.json()).models;
}

export async function createSession() {
  const res = await fetch("/api/sessions", { method: "POST" });
  if (!res.ok) throw new Error("Could not create session");
  const data = await res.json();
  return data.session_id;
}

async function json(res, what) {
  if (res.status === 404) throw new SessionLostError("Session not found");
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail.detail || `${what} failed (HTTP ${res.status})`);
  }
  return res.json();
}

const send = (method, body) => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

// ---- saved chats ----
export const listSessions = () => fetch("/api/sessions").then((r) => json(r, "Listing chats")).then((d) => d.sessions);
export const getSession = (id) => fetch(`/api/sessions/${id}`).then((r) => json(r, "Loading chat"));
export const getHistory = (id) => fetch(`/api/sessions/${id}/history`).then((r) => json(r, "Loading context")).then((d) => d.history);
export const renameSession = (id, title) => fetch(`/api/sessions/${id}`, send("PATCH", { title })).then((r) => json(r, "Rename"));
export const deleteSession = (id) => fetch(`/api/sessions/${id}`, { method: "DELETE" }).then((r) => json(r, "Delete"));

// ---- layers ----
export const updateLayer = (sessionId, layerId, patch) =>
  fetch(`/api/sessions/${sessionId}/layers/${layerId}`, send("PATCH", patch)).then((r) => json(r, "Layer update"));
// Layer geometry comes separately (it can be many MB); fetched only for visible layers.
export const getLayerGeojson = (sessionId, layerId) =>
  fetch(`/api/sessions/${sessionId}/layers/${layerId}/geojson`).then((r) => json(r, "Loading layer"));
export const deleteLayer = (sessionId, layerId) =>
  fetch(`/api/sessions/${sessionId}/layers/${layerId}`, { method: "DELETE" }).then((r) => json(r, "Layer delete"));

export async function uploadFile(sessionId, file) {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`/api/sessions/${sessionId}/upload`, {
    method: "POST",
    body: form,
  });
  if (res.status === 404) throw new SessionLostError("Session expired");
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail.detail || "Upload failed");
  }
  return (await res.json()).layer;
}

// Stream agent events (SSE over POST). Calls onEvent(eventObj) for each event.
// settings = { model, max_steps, temperature }; null values use backend defaults.
export async function streamChat(sessionId, message, settings, onEvent) {
  const res = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, message, ...settings }),
  });
  if (res.status === 404) throw new SessionLostError("Session expired");
  if (!res.ok || !res.body) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail.detail || `Chat request failed (HTTP ${res.status})`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let sep;
    while ((sep = buffer.indexOf("\n\n")) !== -1) {
      const chunk = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      const line = chunk.split("\n").find((l) => l.startsWith("data: "));
      if (!line) continue;
      try {
        onEvent(JSON.parse(line.slice(6)));
      } catch {
        /* ignore malformed chunk */
      }
    }
  }
}
