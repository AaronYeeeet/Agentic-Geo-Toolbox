import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, test, vi } from 'vitest'
import { BUILT_IN_OVERLAYS, type Overlay, useLayerStore } from '@/store/layerStore'
import { ResultActions } from './ResultActions'

const fitBounds = vi.fn()
vi.mock('@/map/mapRef', () => ({ getMap: () => ({ fitBounds }) }))

const result = (id: string, bbox: Overlay['bbox']): Overlay => ({
  id, group: 'results', kind: 'geojson', title: id, visible: true, opacity: 1, removable: true, bbox,
})

beforeEach(() => {
  useLayerStore.setState({ overlays: [...BUILT_IN_OVERLAYS, result('r1', [8.64, 49.86, 8.65, 49.87]), result('r2', [8.66, 49.87, 8.67, 49.88])] })
  fitBounds.mockClear()
})

test('"Zoom to results" fits the union of all result layers of the answer', async () => {
  render(<ResultActions layerIds={['r1', 'r2']} />)

  await userEvent.click(screen.getByRole('button', { name: 'Zoom to results' }))

  expect(fitBounds).toHaveBeenCalledWith([8.64, 49.86, 8.67, 49.88], expect.anything())
})

test('"Hide layer" and "Show layer" toggle the result layers', async () => {
  render(<ResultActions layerIds={['r1']} />)

  await userEvent.click(screen.getByRole('button', { name: 'Hide layer' }))
  expect(useLayerStore.getState().overlays.find((o) => o.id === 'r1')?.visible).toBe(false)

  await userEvent.click(screen.getByRole('button', { name: 'Show layer' }))
  expect(useLayerStore.getState().overlays.find((o) => o.id === 'r1')?.visible).toBe(true)
})

test('renders nothing once the layers were removed', () => {
  const { container } = render(<ResultActions layerIds={['gone']} />)
  expect(container).toBeEmptyDOMElement()
})
