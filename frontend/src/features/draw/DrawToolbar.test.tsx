import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, test, vi } from 'vitest'
import { TooltipProvider } from '@/components/ui/tooltip'
import { useDrawStore } from '@/store/drawStore'
import { useSelectionStore } from '@/store/selectionStore'
import { DrawToolbar } from './DrawToolbar'

vi.mock('@/map/mapRef', () => ({
  getMap: () => ({
    getBounds: () => ({ getWest: () => 8.64, getSouth: () => 49.86, getEast: () => 8.66, getNorth: () => 49.88 }),
  }),
}))

const renderToolbar = () =>
  render(
    <TooltipProvider>
      <DrawToolbar />
    </TooltipProvider>,
  )

beforeEach(() => {
  useSelectionStore.setState({ selection: null })
  useDrawStore.setState({ tool: null })
})

test('the rectangle tool becomes active and shows its hint; clicking again turns it off', async () => {
  renderToolbar()
  const rectangle = screen.getByRole('button', { name: 'Draw a rectangle' })

  await userEvent.click(rectangle)
  expect(useDrawStore.getState().tool).toBe('rectangle')
  expect(rectangle).toHaveAttribute('aria-pressed', 'true')
  expect(screen.getByRole('status')).toHaveTextContent('Esc cancels')

  await userEvent.click(rectangle)
  expect(useDrawStore.getState().tool).toBeNull()
})

test('"use the current view" selects the view and "clear" removes the selection', async () => {
  renderToolbar()

  await userEvent.click(screen.getByRole('button', { name: 'Use the current view' }))
  expect(useSelectionStore.getState().selection?.properties.kind).toBe('view')

  await userEvent.click(screen.getByRole('button', { name: 'Clear selection' }))
  expect(useSelectionStore.getState().selection).toBeNull()
})
