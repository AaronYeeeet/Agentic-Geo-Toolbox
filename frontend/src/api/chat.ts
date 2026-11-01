import type { AgentEvent, ChatRequest } from './protocol'
import { parseSSE } from './sse'

export class ChatHttpError extends Error {
  readonly status: number

  constructor(status: number) {
    super(`POST /api/chat answered ${status}`)
    this.status = status
  }
}

/** Posts a question and calls `onEvent` for every protocol event until the stream ends or `signal` aborts. */
export async function streamChat(
  request: ChatRequest,
  { signal, onEvent }: { signal: AbortSignal; onEvent: (event: AgentEvent) => void },
): Promise<void> {
  const response = await fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify(request),
    signal,
  })
  if (!response.ok || !response.body) throw new ChatHttpError(response.status)
  for await (const message of parseSSE(response.body)) onEvent(message as AgentEvent)
}
