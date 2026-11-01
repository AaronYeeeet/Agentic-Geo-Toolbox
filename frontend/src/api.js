// Thin client for the backend API. All requests go through the Vite proxy (/api).

// Sessions live in backend memory, so a backend restart (e.g. uvicorn --reload)
// invalidates the frontend's session_id. Callers catch this and create a new one.
export class SessionLostError extends Error {}

export async function getHealth() {
  const res = await fetch("/api/health");
  if (!res.ok) throw new Error("Backend not reachable");
  return res.json();
}

export async function createSession() {
  const res = await fetch("/api/sessions", { method: "POST" });
  if (!res.ok) throw new Error("Could not create session");
  const data = await res.json();
  return data.session_id;
}

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
export async function streamChat(sessionId, message, onEvent) {
  const res = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, message }),
  });
  if (res.status === 404) throw new SessionLostError("Session expired");
  if (!res.ok || !res.body) throw new Error(`Chat request failed (HTTP ${res.status})`);

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
