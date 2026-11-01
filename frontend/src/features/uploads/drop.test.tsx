import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import App from '@/App'

const addUploads = vi.fn(async (_files: File[]) => {})
vi.mock('./addUploads', () => ({ addUploads: (files: File[]) => addUploads(files) }))

beforeEach(() => {
  addUploads.mockClear()
  // jsdom has no WebGL; the map shows its fallback message, which is enough for this test.
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null)
})

const files = (name: string) => ({ types: ['Files'], files: [new File(['{}'], name)], dropEffect: 'none' })

test('a file dropped on the chat panel is uploaded, not opened by the browser', () => {
  render(<App />)

  const panel = screen.getByTestId('chat-panel')
  fireEvent.dragEnter(panel, { dataTransfer: files('parks.geojson') })
  const dropped = fireEvent.drop(panel, { dataTransfer: files('parks.geojson') })

  expect(dropped).toBe(false) // default prevented
  expect(addUploads).toHaveBeenCalledWith([expect.objectContaining({ name: 'parks.geojson' })])
})

test('a file dropped anywhere else on the page never makes the browser navigate away', () => {
  render(<App />)

  const event = new Event('drop', { bubbles: true, cancelable: true })
  Object.defineProperty(event, 'dataTransfer', { value: files('x.json') })
  window.dispatchEvent(event)

  expect(event.defaultPrevented).toBe(true)
})
