import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test } from 'vitest'
import i18n from '@/i18n'
import { useSelectionStore } from '@/store/selectionStore'
import { SelectionChip } from './SelectionChip'

const rectangle = {
  type: 'Feature' as const,
  geometry: { type: 'Polygon' as const, coordinates: [[[8.65, 49.87], [8.66, 49.87], [8.66, 49.874], [8.65, 49.87]]] },
  properties: { kind: 'rectangle' as const, area_m2: 420_000 },
}

afterEach(async () => {
  await i18n.changeLanguage('en')
  useSelectionStore.setState({ selection: null })
})

test('shows kind and area in the UI language and can be removed', async () => {
  useSelectionStore.setState({ selection: rectangle })
  const { rerender } = render(<SelectionChip />)
  expect(screen.getByText('Rectangle, 0.42 km²')).toBeInTheDocument()

  await i18n.changeLanguage('de')
  rerender(<SelectionChip />)
  expect(screen.getByText('Rechteck, 0,42 km²')).toBeInTheDocument()

  await userEvent.click(screen.getByRole('button', { name: 'Rechteck, 0,42 km² aus dem Kontext entfernen' }))
  expect(useSelectionStore.getState().selection).toBeNull()
})

test('a picked point shows its name instead of an area', () => {
  useSelectionStore.setState({
    selection: { type: 'Feature', geometry: { type: 'Point', coordinates: [8.65, 49.87] }, properties: { kind: 'feature', area_m2: 0, label: 'Demo school 1' } },
  })
  render(<SelectionChip />)

  expect(screen.getByText('Feature, Demo school 1')).toBeInTheDocument()
})

test('renders nothing without a selection', () => {
  const { container } = render(<SelectionChip />)
  expect(container).toBeEmptyDOMElement()
})

test('a selection without area or name shows just its kind, without a dangling comma', () => {
  useSelectionStore.setState({
    selection: { type: 'Feature', geometry: { type: 'Point', coordinates: [8.65, 49.87] }, properties: { kind: 'feature', area_m2: 0 } },
  })
  render(<SelectionChip />)

  expect(screen.getByTestId('selection-chip')).toHaveTextContent(/^Feature$/)
})
