import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { TooltipProvider } from '@/components/ui/tooltip'
import { useSelectionStore } from '@/store/selectionStore'
import { SearchBox } from './SearchBox'

const flyTo = vi.fn()
const fitBounds = vi.fn()
vi.mock('@/map/mapRef', () => ({
  getMap: () => ({ flyTo, fitBounds, getCenter: () => ({ lng: 8.65, lat: 49.87 }), getZoom: () => 16 }),
}))

const photonAnswer = {
  features: [
    {
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [8.65989, 49.87425] },
      properties: { name: 'Fraunhofer IGD', countrycode: 'DE', osm_key: 'building', osm_value: 'office', street: 'Fraunhoferstraße', housenumber: '5', city: 'Darmstadt', state: 'Hessen' },
    },
  ],
}

let fetchMock: ReturnType<typeof vi.spyOn>

beforeEach(() => {
  fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async () => new Response(JSON.stringify(photonAnswer)))
  useSelectionStore.setState({ selection: null })
})
afterEach(() => vi.restoreAllMocks())

const renderBox = () =>
  render(
    <TooltipProvider>
      <SearchBox />
    </TooltipProvider>,
  )

test('waits for three characters and debounces typing into one request', async () => {
  renderBox()
  const input = screen.getByRole('combobox', { name: 'Search places' })

  await userEvent.type(input, 'Fr')
  await new Promise((r) => setTimeout(r, 400))
  expect(fetchMock).not.toHaveBeenCalled()

  await userEvent.type(input, 'aunhofer IGD')
  await waitFor(() => expect(screen.getByRole('option', { name: /Fraunhofer IGD/ })).toBeInTheDocument())
  expect(fetchMock).toHaveBeenCalledTimes(1)
  expect(screen.getByText('Search by Photon (komoot), data © OpenStreetMap contributors')).toBeInTheDocument()
})

test('Enter on a highlighted result flies there', async () => {
  renderBox()
  await userEvent.type(screen.getByRole('combobox', { name: 'Search places' }), 'Fraunhofer')
  await screen.findByRole('option', { name: /Fraunhofer IGD/ })

  await userEvent.keyboard('{ArrowDown}{Enter}')

  expect(flyTo).toHaveBeenCalledWith(expect.objectContaining({ center: [8.65989, 49.87425] }))
  expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
})

test('a result can become the selection', async () => {
  renderBox()
  await userEvent.type(screen.getByRole('combobox', { name: 'Search places' }), 'Fraunhofer')
  await screen.findByRole('option', { name: /Fraunhofer IGD/ })

  await userEvent.click(screen.getByRole('button', { name: 'Use as selection' }))

  expect(useSelectionStore.getState().selection?.properties).toMatchObject({ kind: 'search', label: 'Fraunhofer IGD' })
  expect(fitBounds).toHaveBeenCalled()
})
