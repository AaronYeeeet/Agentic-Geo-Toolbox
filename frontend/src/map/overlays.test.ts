import type { FeatureCollection } from 'geojson'
import type { LayerSpecification } from '@maplibre/maplibre-gl-style-spec'
import { describe, expect, test } from 'vitest'
import type { Overlay } from '@/store/layerStore'
import type { SelectionFeature } from '@/store/selectionStore'
import { FakeMap } from './fakeMap'
import { type MapLike, reconcileOverlays } from './overlays'

const BASEMAP: LayerSpecification[] = [
  { id: 'background', type: 'background' },
  { id: 'roads', type: 'line', source: 'basemap', 'source-layer': 'transportation' },
  { id: 'place-labels', type: 'symbol', source: 'basemap', 'source-layer': 'place' },
]

const points: FeatureCollection = {
  type: 'FeatureCollection',
  features: [{ type: 'Feature', geometry: { type: 'Point', coordinates: [8.66, 49.874] }, properties: { id: 'a' } }],
}

const result: Overlay = {
  id: 'result-1',
  group: 'results',
  kind: 'geojson',
  title: 'Schools (Demo data)',
  visible: true,
  opacity: 1,
  color: '#2563eb',
  removable: true,
  data: points,
  demo: true,
}

const wms: Overlay = {
  id: 'wms-1',
  group: 'aerial',
  kind: 'wms',
  title: 'Aerial',
  visible: true,
  opacity: 0.8,
  removable: true,
  wms: { url: 'https://example.org/wms', layers: ['dop'] },
}

const terrain: Overlay = {
  id: 'terrain3d',
  group: 'terrain',
  kind: 'terrain',
  title: '',
  visible: true,
  opacity: 1,
  removable: false,
}

const selection: SelectionFeature = {
  type: 'Feature',
  geometry: {
    type: 'Polygon',
    coordinates: [[[8.65, 49.87], [8.67, 49.87], [8.67, 49.88], [8.65, 49.88], [8.65, 49.87]]],
  },
  properties: { kind: 'rectangle', area_m2: 1_000_000 },
}

const asMap = (fake: FakeMap) => fake as unknown as MapLike

describe('reconcileOverlays', () => {
  test('adds visible overlays below the basemap labels and the selection on top', () => {
    const map = new FakeMap(BASEMAP)

    reconcileOverlays(asMap(map), { overlays: [wms, result], selection })

    const ids = map.ids()
    expect(ids.indexOf('gt-wms-wms-1')).toBeLessThan(ids.indexOf('place-labels'))
    expect(ids.indexOf('gt-geojson-result-1-circle')).toBeLessThan(ids.indexOf('place-labels'))
    expect(ids.indexOf('gt-wms-wms-1')).toBeLessThan(ids.indexOf('gt-geojson-result-1-circle'))
    expect(ids.at(-1)).toMatch(/^gt-selection/)
  })

  test('re-adds every overlay, the selection and the terrain after a style reload', () => {
    const map = new FakeMap(BASEMAP)
    const state = { overlays: [terrain, wms, result], selection }
    reconcileOverlays(asMap(map), state)
    const before = map.ids()

    map.reloadStyle(BASEMAP)
    reconcileOverlays(asMap(map), state)

    expect(map.ids()).toEqual(before)
    expect(map.getTerrain()).toMatchObject({ source: 'gt-dem-terrain' })
  })

  test('keeps the selection on top in a style without symbol layers (aerial)', () => {
    const map = new FakeMap([{ id: 'imagery', type: 'background' }])
    reconcileOverlays(asMap(map), { overlays: [], selection })

    reconcileOverlays(asMap(map), { overlays: [result], selection })

    expect(map.ids().at(-1)).toMatch(/^gt-selection/)
    expect(map.ids().indexOf('gt-geojson-result-1-circle')).toBeGreaterThan(0)
  })

  test('every style gets a calm sky, so tilted views have a horizon instead of page background', () => {
    const map = new FakeMap(BASEMAP)

    reconcileOverlays(asMap(map), { overlays: [], selection: null })
    expect(map.getSky()).toMatchObject({ 'sky-color': expect.any(String) })

    map.reloadStyle(BASEMAP)
    reconcileOverlays(asMap(map), { overlays: [terrain], selection: null })
    expect(map.getSky()).toMatchObject({ 'sky-color': expect.any(String) })
  })

  test('removes overlays that are no longer in the state', () => {
    const map = new FakeMap(BASEMAP)
    reconcileOverlays(asMap(map), { overlays: [terrain, wms, result], selection })

    reconcileOverlays(asMap(map), { overlays: [], selection: null })

    expect(map.ids()).toEqual(BASEMAP.map((l) => l.id))
    expect(Object.keys(map.sources)).toEqual([])
    expect(map.getTerrain()).toBeNull()
  })

  test('attributions reach MapLibre (which renders HTML) escaped', () => {
    const map = new FakeMap(BASEMAP)

    reconcileOverlays(asMap(map), { overlays: [{ ...wms, attribution: '<img src=x onerror=alert(1)> © Agent' }], selection: null })

    const spec = map.getSource('gt-wms-wms-1')?.spec as { attribution?: string }
    expect(spec.attribution).toBe('&lt;img src=x onerror=alert(1)&gt; © Agent')
  })

  test('hides a layer instead of removing it, and applies opacity', () => {
    const map = new FakeMap(BASEMAP)
    reconcileOverlays(asMap(map), { overlays: [wms], selection: null })

    reconcileOverlays(asMap(map), { overlays: [{ ...wms, visible: false, opacity: 0.4 }], selection: null })

    const layer = map.getLayer('gt-wms-wms-1') as { layout?: Record<string, unknown>; paint?: Record<string, unknown> }
    expect(layer.layout?.visibility).toBe('none')
    expect(layer.paint?.['raster-opacity']).toBe(0.4)
  })

  test('updates GeoJSON data only when it changed', () => {
    const map = new FakeMap(BASEMAP)
    reconcileOverlays(asMap(map), { overlays: [result], selection: null })
    reconcileOverlays(asMap(map), { overlays: [result], selection: null })
    expect(map.setDataCalls).toBe(0)

    const changed = { ...result, data: { ...points, features: [] } }
    reconcileOverlays(asMap(map), { overlays: [changed], selection: null })

    expect(map.setDataCalls).toBe(1)
  })

  test('highlights only the requested features of a layer', () => {
    const map = new FakeMap(BASEMAP)

    reconcileOverlays(asMap(map), { overlays: [{ ...result, highlightIds: ['a'] }], selection: null })

    const highlight = map.getLayer('gt-geojson-result-1-highlight-circle') as { filter?: unknown }
    expect(JSON.stringify(highlight.filter)).toContain('"a"')
  })
})
