import { create } from 'zustand'
import { ChatHttpError, streamChat } from '@/api/chat'
import type { AgentEvent, ChatMessageIn, MapAction, SourceItem } from '@/api/protocol'
import { buildChatContext } from '@/features/chat/context'
import i18n from '@/i18n'

export interface ToolStep {
  id: string
  name: string
  label: string
  status: 'running' | 'ok' | 'error' | 'stopped'
  summary?: string
  durationMs?: number
}

export interface UserMessage {
  id: string
  role: 'user'
  text: string
}

export interface AssistantMessage {
  id: string
  role: 'assistant'
  /** The question this answers (used by "Try again"). */
  question: string
  text: string
  steps: ToolStep[]
  sources: SourceItem[]
  resultLayerIds: string[]
  status: 'streaming' | 'done' | 'stopped' | 'error'
  error?: { message: string; retryable: boolean }
}

export type ChatMessage = UserMessage | AssistantMessage

/** Map actions from the stream go to this handler (set by map/actions.ts), keeping the store map-free. */
let mapActionHandler: (action: MapAction) => void = () => {}
export function setMapActionHandler(handler: (action: MapAction) => void): void {
  mapActionHandler = handler
}

/** Steps still running when an answer ends were cut off: stopped by the user, or failed with the stream. */
function closeSteps(message: AssistantMessage, status: 'stopped' | 'error'): AssistantMessage {
  return { ...message, steps: message.steps.map((step) => (step.status === 'running' ? { ...step, status } : step)) }
}

const newId = () => globalThis.crypto?.randomUUID?.() ?? `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`
let controller: AbortController | null = null

function applyEvent(message: AssistantMessage, event: AgentEvent): AssistantMessage {
  switch (event.event) {
    case 'text_delta':
      return { ...message, text: message.text + event.data.text }
    case 'tool_start':
      return {
        ...message,
        steps: [...message.steps, { id: event.data.id, name: event.data.name, label: event.data.label, status: 'running' }],
      }
    case 'tool_end':
      return {
        ...message,
        steps: message.steps.map((step) =>
          step.id === event.data.id
            ? { ...step, status: event.data.status, summary: event.data.summary, durationMs: event.data.duration_ms }
            : step,
        ),
      }
    case 'map_action':
      return event.data.type === 'add_geojson_layer'
        ? { ...message, resultLayerIds: [...message.resultLayerIds, event.data.id] }
        : message
    case 'sources':
      return { ...message, sources: event.data.items }
    case 'error':
      return { ...message, error: { message: event.data.message, retryable: event.data.retryable } }
    default:
      return message
  }
}

interface ChatState {
  conversationId: string
  messages: ChatMessage[]
  streaming: boolean
  /** Uploads the user removed from the context (their layers stay on the map). */
  excludedUploads: string[]
  send: (text: string) => Promise<void>
  retry: (assistantId: string) => Promise<void>
  stop: () => void
  reset: () => void
  excludeUpload: (id: string) => void
}

export const useChatStore = create<ChatState>()((set, get) => {
  const update = (id: string, change: (message: AssistantMessage) => AssistantMessage) =>
    set((state) => ({
      messages: state.messages.map((m) => (m.id === id && m.role === 'assistant' ? change(m) : m)),
    }))

  const ask = async (question: string) => {
    const answer: AssistantMessage = {
      id: newId(),
      role: 'assistant',
      question,
      text: '',
      steps: [],
      sources: [],
      resultLayerIds: [],
      status: 'streaming',
    }
    const history: ChatMessageIn[] = get()
      .messages.flatMap((m): ChatMessageIn[] =>
        m.role === 'user' ? [{ role: 'user', content: m.text }] : m.status === 'done' ? [{ role: 'assistant', content: m.text }] : [],
      )
      .slice(-12)
    set((state) => ({ messages: [...state.messages, answer], streaming: true }))
    const own = new AbortController()
    controller = own
    let finished = false
    try {
      await streamChat(
        { conversation_id: get().conversationId, messages: history, context: buildChatContext(get().excludedUploads) },
        {
          signal: own.signal,
          onEvent: (event) => {
            if (event.event === 'done') finished = true
            if (event.event === 'map_action') {
              try {
                mapActionHandler(event.data)
              } catch (error) {
                console.warn('[chat] map action failed', event.data.type, error)
              }
            }
            update(answer.id, (m) => applyEvent(m, event))
          },
        },
      )
      update(answer.id, (m) =>
        finished
          ? { ...m, status: m.error ? 'error' : 'done' }
          : { ...closeSteps(m, 'error'), status: 'error', error: { message: i18n.t('chat.errors.stream'), retryable: true } },
      )
    } catch (error) {
      if (own.signal.aborted) update(answer.id, (m) => ({ ...closeSteps(m, 'stopped'), status: 'stopped' }))
      else {
        const message =
          error instanceof ChatHttpError ? i18n.t('chat.errors.http', { status: error.status }) : i18n.t('chat.errors.network')
        update(answer.id, (m) => ({ ...closeSteps(m, 'error'), status: 'error', error: { message, retryable: true } }))
      }
    } finally {
      if (controller === own) controller = null
      set({ streaming: false })
    }
  }

  return {
    conversationId: newId(),
    messages: [],
    streaming: false,
    excludedUploads: [],
    send: async (text) => {
      const question = text.trim()
      if (!question || get().streaming) return
      set((state) => ({ messages: [...state.messages, { id: newId(), role: 'user', text: question }] }))
      await ask(question)
    },
    retry: async (assistantId) => {
      const target = get().messages.find((m) => m.id === assistantId)
      if (!target || target.role !== 'assistant' || get().streaming) return
      set((state) => ({ messages: state.messages.filter((m) => m.id !== assistantId) }))
      await ask(target.question)
    },
    stop: () => controller?.abort(),
    reset: () => {
      controller?.abort()
      set({ conversationId: newId(), messages: [], streaming: false, excludedUploads: [] })
    },
    excludeUpload: (id) => set((state) => ({ excludedUploads: [...state.excludedUploads, id] })),
  }
})
