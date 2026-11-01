import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { TooltipProvider } from '@/components/ui/tooltip'
import { type AssistantMessage, useChatStore } from '@/store/chatStore'
import { useSelectionStore } from '@/store/selectionStore'
import { ChatPanel } from './ChatPanel'

const renderPanel = () =>
  render(
    <TooltipProvider>
      <ChatPanel variant="dock" />
    </TooltipProvider>,
  )

const send = vi.fn(async () => {})
const stop = vi.fn()
const retry = vi.fn(async () => {})

beforeEach(() => {
  useChatStore.getState().reset()
  useChatStore.setState({ send, stop, retry })
  useSelectionStore.setState({ selection: null })
})
afterEach(() => vi.clearAllMocks())

test('the empty state offers four example prompts that send right away', async () => {
  renderPanel()

  const examples = screen.getAllByRole('button', { name: /area|schools|chargers|Fraunhofer/i })
  expect(examples.length).toBeGreaterThanOrEqual(4)
  await userEvent.click(screen.getByRole('button', { name: 'Show all schools in the selected area.' }))
  expect(send).toHaveBeenCalledWith('Show all schools in the selected area.')
})

test('Enter sends, Shift+Enter adds a line, and the input clears', async () => {
  renderPanel()
  const input = screen.getByRole('textbox', { name: 'Ask about this area' })

  await userEvent.type(input, 'first line{Shift>}{Enter}{/Shift}second line')
  expect(input).toHaveValue('first line\nsecond line')
  expect(send).not.toHaveBeenCalled()

  await userEvent.keyboard('{Enter}')
  expect(send).toHaveBeenCalledWith('first line\nsecond line')
  expect(input).toHaveValue('')
})

test('while streaming the send button becomes a stop button', async () => {
  useChatStore.setState({ streaming: true })
  renderPanel()

  await userEvent.click(screen.getByRole('button', { name: 'Stop' }))
  expect(stop).toHaveBeenCalled()
})

test('the selection appears as a context chip in the composer', () => {
  useSelectionStore.setState({
    selection: {
      type: 'Feature',
      geometry: { type: 'Polygon', coordinates: [[[8.65, 49.87], [8.66, 49.87], [8.66, 49.874], [8.65, 49.87]]] },
      properties: { kind: 'polygon', area_m2: 8420 },
    },
  })
  renderPanel()

  const context = screen.getByRole('group', { name: 'Context for your question' })
  expect(within(context).getByText('Polygon, 8,420 m²')).toBeInTheDocument()
})

test('an answer shows its steps, text, sources and a retry for errors', async () => {
  const answer: AssistantMessage = {
    id: 'a1',
    role: 'assistant',
    question: 'Simulate an error',
    text: 'Partial answer',
    steps: [
      { id: 't1', name: 'resolve_area', label: 'Reading the selected area', status: 'ok', summary: '1.20 km² (rectangle)', durationMs: 310 },
      { id: 't2', name: 'osm_features', label: 'Querying OpenStreetMap (Overpass)', status: 'error', summary: 'Overpass is busy (simulated)', durationMs: 712 },
    ],
    sources: [{ title: 'OpenStreetMap (simulated)', url: 'https://www.openstreetmap.org/copyright', license: 'ODbL 1.0' }],
    resultLayerIds: [],
    status: 'error',
    error: { message: 'Overpass is busy. Try again in a minute.', retryable: true },
  }
  useChatStore.setState({ messages: [{ id: 'u1', role: 'user', text: 'Simulate an error' }, answer] })
  renderPanel()

  expect(screen.getByText('Reading the selected area')).toBeInTheDocument()
  expect(screen.getByText('Overpass is busy (simulated)')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: /OpenStreetMap \(simulated\)/ })).toHaveAttribute('href', 'https://www.openstreetmap.org/copyright')
  expect(screen.getByRole('alert')).toHaveTextContent('Overpass is busy. Try again in a minute.')

  await userEvent.click(screen.getByRole('button', { name: 'Try again' }))
  expect(retry).toHaveBeenCalledWith('a1')
})
