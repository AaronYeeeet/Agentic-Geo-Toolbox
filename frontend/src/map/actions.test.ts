import { beforeEach, describe, expect, test, vi } from 'vitest'
import { BUILT_IN_OVERLAYS, useLayerStore } from '@/store/layerStore'
import { useMapStore } from '@/store/mapStore'
import { executeMapAction } from './actions'

const flyTo = vi.fn()
const fitBounds = vi.fn()
vi.mock('./mapRef', () => ({ getMap: () => ({ flyTo, fitBounds }) }))

const schools = {
  type: 'FeatureCollection' as const,
  features: [
    { type: 'Feature' as const, geometry: { type: 'Point' as const, coordinates: [8.65, 49.87] }, properties: { id: 'school-1' } },
    { type: 'Feature' as const, geometry: { type: 'Point' as const, coordinates: [8.66, 49.88] }, properties: { id: 'school-2' } },
  ],
}
const overlay = (id: string) => useLayerStore.getState().overlays.find((o) => o.id === id)

describe('executeMapAction', () => {
  beforeEach(() => {
    useLayerStore.setState({ overlays: BUILT_IN_OVERLAYS })
    useMapStore.setState({ basemap: 'osm', viewMode: '2d' })
    flyTo.mockClear()
    fitBounds.mockClear()
  })

  test('camera actions move the map', () => {
    executeMapAction({ type: 'fly_to', center: [6.9583, 50.9413], zoom: 16.5 })
    executeMapAction({ type: 'fit_bounds', bbox: [8.64, 49.86, 8.66, 49.88] })

    expect(flyTo).toHaveBeenCalledWith(expect.objectContaining({ center: [6.9583, 50.9413], zoom: 16.5 }))
    expect(fitBounds).toHaveBeenCalledWith([8.64, 49.86, 8.66, 49.88], expect.objectContaining({ maxZoom: 17 }))
  })

  test('add_geojson_layer adds a removable result with bbox, count and demo flag; layer actions update it', () => {
    executeMapAction({ type: 'add_geojson_layer', id: 'result-1', title: 'Schools (Demo data)', geojson: schools, color: '#2563eb', kind: 'demo' })
    expect(overlay('result-1')).toMatchObject({
      group: 'results', kind: 'geojson', visible: true, removable: true, demo: true, featureCount: 2,
      geometryTypes: ['Point'], bbox: [8.65, 49.87, 8.66, 49.88], color: '#2563eb',
    })

    executeMapAction({ type: 'highlight_features', layer_id: 'result-1', feature_ids: ['school-2'] })
    executeMapAction({ type: 'set_layer_visibility', id: 'result-1', visible: false })
    expect(overlay('result-1')).toMatchObject({ highlightIds: ['school-2'], visible: false })

    executeMapAction({ type: 'remove_layer', id: 'result-1' })
    expect(overlay('result-1')).toBeUndefined()
  })

  test('add_wms_layer adds a WMS overlay in the aerial group', () => {
    executeMapAction({ type: 'add_wms_layer', id: 'wms-1', title: 'Topographic map', url: 'https://example.org/wms', layers: ['he_dtk'], attribution: '© HVBG' })

    expect(overlay('wms-1')).toMatchObject({ group: 'aerial', kind: 'wms', wms: { url: 'https://example.org/wms', layers: ['he_dtk'] }, attribution: '© HVBG' })
  })

  test('add_wms_layer ignores URLs that are not http(s)', () => {
    executeMapAction({ type: 'add_wms_layer', id: 'wms-bad', title: 'Bad', url: 'javascript:alert(1)', layers: ['x'], attribution: '' })

    expect(overlay('wms-bad')).toBeUndefined()
  })

  test('basemap and view mode actions go to the map store', () => {
    executeMapAction({ type: 'set_basemap', id: 'aerial' })
    executeMapAction({ type: 'set_view_mode', mode: '3d' })

    expect(useMapStore.getState()).toMatchObject({ basemap: 'aerial', viewMode: '3d' })
  })

  test('actions on unknown layers are ignored without throwing', () => {
    expect(() => {
      executeMapAction({ type: 'remove_layer', id: 'nope' })
      executeMapAction({ type: 'set_layer_visibility', id: 'nope', visible: true })
      executeMapAction({ type: 'highlight_features', layer_id: 'nope', feature_ids: ['x'] })
    }).not.toThrow()
    expect(useLayerStore.getState().overlays).toEqual(BUILT_IN_OVERLAYS)
  })
})
