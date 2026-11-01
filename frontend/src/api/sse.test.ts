import { expect, test } from 'vitest'
import { parseSSE } from './sse'

function streamOf(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder()
  return new ReadableStream({
    start(controller) {
      chunks.forEach((chunk) => controller.enqueue(encoder.encode(chunk)))
      controller.close()
    },
  })
}

async function collect(stream: ReadableStream<Uint8Array>) {
  const events = []
  for await (const event of parseSSE(stream)) events.push(event)
  return events
}

test('parses events split across chunks, including a split multi-byte character', async () => {
  const bytes = new TextEncoder().encode('event: text_delta\ndata: {"text":"Größe"}\n\nevent: done\ndata: {}\n\n')
  const cut = bytes.indexOf(0xc3) + 1 // inside the "ö"
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(bytes.slice(0, 9))
      controller.enqueue(bytes.slice(9, cut))
      controller.enqueue(bytes.slice(cut))
      controller.close()
    },
  })

  expect(await collect(stream)).toEqual([
    { event: 'text_delta', data: { text: 'Größe' } },
    { event: 'done', data: {} },
  ])
})

test('accepts CRLF line endings and several events in one chunk', async () => {
  const events = await collect(streamOf(['event: run_start\r\ndata: {"run_id":"r1"}\r\n\r\nevent: done\r\ndata: {}\r\n\r\n']))

  expect(events.map((e) => e.event)).toEqual(['run_start', 'done'])
})

test('ignores comments and an unfinished trailing event', async () => {
  const events = await collect(streamOf([': keep-alive\n\nevent: done\ndata: {}\n\nevent: text_delta\ndata: {"te']))

  expect(events).toEqual([{ event: 'done', data: {} }])
})
