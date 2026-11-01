import { afterEach, describe, expect, test, vi } from 'vitest'
import { searchPhoton, selectionFromResult } from './photon'

const feature = (name: string, countrycode: string, extra: Record<string, unknown> = {}) => ({
  type: 'Feature',
  geometry: { type: 'Point', coordinates: [6.9583, 50.9413] },
  properties: { name, countrycode, osm_key: 'amenity', osm_value: 'place_of_worship', city: 'Köln', state: 'Nordrhein-Westfalen', country: 'Deutschland', ...extra },
})

describe('searchPhoton', () => {
  afterEach(() => vi.restoreAllMocks())

  test('asks Photon in the UI language with a bias to the current view', async () => {
    const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ features: [] })))

    await searchPhoton('Kölner Dom', { lang: 'de', center: [8.65989, 49.87425], zoom: 16 })

    const url = new URL(String(fetch.mock.calls[0][0]))
    expect(url.origin + url.pathname).toBe('https://photon.komoot.io/api/')
    expect(url.searchParams.get('q')).toBe('Kölner Dom')
    expect(url.searchParams.get('lang')).toBe('de')
    expect(url.searchParams.get('lat')).toBe('49.87425')
    expect(url.searchParams.get('lon')).toBe('8.65989')
  })

  test('ranks results in Germany first and converts the [W, N, E, S] extent', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({
          features: [
            feature('Dom Paris', 'FR', { city: 'Paris', state: undefined, country: 'France' }),
            feature('Kölner Dom', 'DE', { extent: [6.9576, 50.9418, 6.9591, 50.9408] }),
          ],
        }),
      ),
    )

    const results = await searchPhoton('Dom', { lang: 'en', center: [8.65, 49.87], zoom: 12 })

    expect(results.map((r) => r.name)).toEqual(['Kölner Dom', 'Dom Paris'])
    expect(results[0].bbox).toEqual([6.9576, 50.9408, 6.9591, 50.9418])
    expect(results[0].detail).toBe('Köln, Nordrhein-Westfalen')
    expect(results[1].detail).toBe('Paris, France')
  })
})

test('a result without extent becomes a 200 m box selection, with area and label', () => {
  const selection = selectionFromResult({ id: 'x', name: 'IGD', detail: '', center: [8.65989, 49.87425], kind: 'building' })

  expect(selection.properties.kind).toBe('search')
  expect(selection.properties.label).toBe('IGD')
  expect(selection.properties.area_m2).toBeGreaterThan(35_000)
  expect(selection.properties.area_m2).toBeLessThan(45_000)
})
