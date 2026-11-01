import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import type { MapAction } from '@/api/protocol'
import i18n from '@/i18n'
import { type AssistantMessage, setMapActionHandler, useChatStore } from './chatStore'

function sse(events: [string, unknown][]) {
  return events.map(([event, data]) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`).join('')
}

const STREAM = sse([
  ['run_start', { run_id: 'r1' }],
  ['tool_start', { id: 't1', name: 'osm_features', label: 'Searching OpenStreetMap for schools' }],
  ['tool_end', { id: 't1', status: 'ok', summary: '6 schools (demo data)', duration_ms: 412 }],
  ['map_action', { type: 'add_geojson_layer', id: 'result-1', title: 'Schools (Demo data)', geojson: { type: 'FeatureCollection', features: [] }, color: '#2563eb', kind: 'demo' }],
  ['text_delta', { text: 'I found ' }],
  ['text_delta', { text: '6 schools.' }],
  ['sources', { items: [{ title: 'OpenStreetMap (simulated)', url: 'https://www.openstreetmap.org/copyright', license: 'ODbL 1.0' }] }],
  ['done', {}],
])

const lastAssistant = () => useChatStore.getState().messages.at(-1) as AssistantMessage

describe('chat store', () => {
  const actions: MapAction[] = []

  beforeEach(() => {
    useChatStore.getState().reset()
    actions.length = 0
    setMapActionHandler((action) => actions.push(action))
  })
  afterEach(() => vi.restoreAllMocks())

  test('a streamed answer collects text, steps, sources and result layers, and runs map actions', async () => {
    const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(STREAM, { status: 200 }))

    await useChatStore.getState().send('Show all schools in the selected area.')

    const body = JSON.parse(fetch.mock.calls[0][1]?.body as string)
    expect(body.messages.at(-1)).toEqual({ role: 'user', content: 'Show all schools in the selected area.' })
    expect(body.context.ui_language).toBe('en')
    const answer = lastAssistant()
    expect(answer).toMatchObject({ status: 'done', text: 'I found 6 schools.', resultLayerIds: ['result-1'] })
    expect(answer.steps).toEqual([
      { id: 't1', name: 'osm_features', label: 'Searching OpenStreetMap for schools', status: 'ok', summary: '6 schools (demo data)', durationMs: 412 },
    ])
    expect(answer.sources[0].license).toBe('ODbL 1.0')
    expect(actions.map((a) => a.type)).toEqual(['add_geojson_layer'])
    expect(useChatStore.getState().streaming).toBe(false)
  })

  test('stop aborts the request and marks the answer as stopped', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(
      (_input, init) =>
        new Promise((_resolve, reject) => {
          init?.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
        }),
    )

    const pending = useChatStore.getState().send('Hello')
    useChatStore.getState().stop()
    await pending

    expect(lastAssistant().status).toBe('stopped')
    expect(useChatStore.getState().streaming).toBe(false)
  })

  test('stopping during a tool step marks that step as stopped instead of leaving it running', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation((_input, init) => {
      const body = new ReadableStream<Uint8Array>({
        start(controller) {
          controller.enqueue(new TextEncoder().encode(sse([['run_start', { run_id: 'r5' }], ['tool_start', { id: 't1', name: 'osm_features', label: 'Searching' }]])))
          init?.signal?.addEventListener('abort', () => controller.error(new DOMException('aborted', 'AbortError')))
        },
      })
      return Promise.resolve(new Response(body))
    })

    const pending = useChatStore.getState().send('Hello')
    await vi.waitFor(() => expect(lastAssistant().steps).toHaveLength(1))
    useChatStore.getState().stop()
    await pending

    expect(lastAssistant().status).toBe('stopped')
    expect(lastAssistant().steps.map((s) => s.status)).toEqual(['stopped'])
  })

  test('an interrupted stream marks an open step as failed', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(sse([['run_start', { run_id: 'r6' }], ['tool_start', { id: 't1', name: 'osm_features', label: 'Searching' }]])),
    )

    await useChatStore.getState().send('Hello')

    expect(lastAssistant().steps.map((s) => s.status)).toEqual(['error'])
  })

  test('an HTTP error becomes a retryable error in the UI language', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('boom', { status: 500 }))

    await useChatStore.getState().send('Hello')

    expect(lastAssistant()).toMatchObject({ status: 'error', error: { retryable: true } })
    expect(lastAssistant().error?.message).toBe(i18n.t('chat.errors.http', { status: 500 }))
  })

  test('an unreachable backend becomes a network error, and retry asks again', async () => {
    const fetch = vi.spyOn(globalThis, 'fetch').mockRejectedValueOnce(new TypeError('Failed to fetch'))
    await useChatStore.getState().send('Hello')
    expect(lastAssistant().error?.message).toBe(i18n.t('chat.errors.network'))

    fetch.mockResolvedValueOnce(new Response(sse([['run_start', { run_id: 'r2' }], ['text_delta', { text: 'Hi' }], ['done', {}]])))
    await useChatStore.getState().retry(lastAssistant().id)

    expect(lastAssistant()).toMatchObject({ status: 'done', text: 'Hi' })
    expect(useChatStore.getState().messages.filter((m) => m.role === 'user')).toHaveLength(1)
  })

  test('an error event from the agent is shown with its own message', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(sse([['run_start', { run_id: 'r3' }], ['error', { message: 'Overpass is busy. Try again in a minute.', retryable: true }], ['done', {}]])),
    )

    await useChatStore.getState().send('Simulate an error')

    expect(lastAssistant()).toMatchObject({ status: 'error', error: { message: 'Overpass is busy. Try again in a minute.', retryable: true } })
  })

  test('a stream that ends without done is reported as interrupted', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(sse([['run_start', { run_id: 'r4' }], ['text_delta', { text: 'I fou' }]])))

    await useChatStore.getState().send('Hello')

    expect(lastAssistant()).toMatchObject({ status: 'error', text: 'I fou', error: { message: i18n.t('chat.errors.stream') } })
  })
})
