import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, test } from 'vitest'
import { TooltipProvider } from '@/components/ui/tooltip'
import { BUILT_IN_OVERLAYS, type Overlay, useLayerStore } from '@/store/layerStore'
import { LayerPanel } from './LayerPanel'

const schools: Overlay = {
  id: 'result-schools-1',
  group: 'results',
  kind: 'geojson',
  title: 'Schools (Demo data)',
  visible: true,
  opacity: 1,
  color: '#2563eb',
  removable: true,
  demo: true,
  featureCount: 6,
  geometryTypes: ['Point'],
  data: { type: 'FeatureCollection', features: [] },
}

const overlay = (id: string) => useLayerStore.getState().overlays.find((o) => o.id === id)

function renderPanel() {
  return render(
    <TooltipProvider>
      <LayerPanel />
    </TooltipProvider>,
  )
}

beforeEach(() => {
  useLayerStore.setState({ overlays: BUILT_IN_OVERLAYS })
})

test('lists the layer groups with the built-in layers', () => {
  renderPanel()

  for (const group of ['Terrain', 'Buildings', 'Aerial and WMS', 'My data', 'Agent results']) {
    expect(screen.getByRole('heading', { name: group })).toBeInTheDocument()
  }
  expect(screen.getByRole('switch', { name: 'Show 3D terrain' })).not.toBeChecked()
  expect(screen.getByRole('switch', { name: 'Show Buildings 2.5D' })).toBeInTheDocument()
  expect(screen.getByRole('switch', { name: 'Show 3D buildings (LoD2)' })).toBeDisabled()
  expect(screen.getByText('Drop a file on the map or use the paperclip in the chat.')).toBeInTheDocument()
})

test('the switch toggles visibility and a visible layer offers an opacity slider', async () => {
  renderPanel()

  await userEvent.click(screen.getByRole('switch', { name: 'Show Hillshade' }))
  expect(overlay('hillshade')?.visible).toBe(true)

  const slider = screen.getByRole('slider', { name: 'Opacity of Hillshade' })
  slider.focus()
  await userEvent.keyboard('{ArrowLeft}')
  expect(overlay('hillshade')?.opacity).toBeCloseTo(0.55)
})

test('agent results show their feature count and demo badge, and can be removed', async () => {
  useLayerStore.getState().addOverlay(schools)
  renderPanel()

  const results = screen.getByRole('region', { name: 'Agent results' })
  expect(within(results).getByText('Schools (Demo data)')).toBeInTheDocument()
  expect(within(results).getByText('Demo data')).toBeInTheDocument()
  expect(within(results).getByText('6 features')).toBeInTheDocument()

  await userEvent.click(within(results).getByRole('button', { name: 'Remove Schools (Demo data)' }))
  expect(overlay('result-schools-1')).toBeUndefined()
})
