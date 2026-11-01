import { bbox as turfBbox } from '@turf/turf'
import type { FeatureCollection } from 'geojson'
import type { MapAction } from '@/api/protocol'
import { isHttpUrl } from '@/lib/safe'
import { type BBox, useLayerStore } from '@/store/layerStore'
import { useMapStore } from '@/store/mapStore'
import { mapPadding } from './camera'
import { getMap } from './mapRef'

function bboxOf(collection: FeatureCollection): BBox | undefined {
  if (collection.features.length === 0) return undefined
  const [west, south, east, north] = turfBbox(collection)
  return [west, south, east, north]
}

/**
 * Applies one map action from the agent stream. Layer actions go through the stores, so the
 * reconciler draws them and they survive basemap switches; actions on unknown layers do nothing.
 */
export function executeMapAction(action: MapAction): void {
  const map = getMap()
  const layers = useLayerStore.getState()
  switch (action.type) {
    case 'fly_to':
      map?.flyTo({ center: action.center, zoom: action.zoom, duration: 1600, essential: true })
      return
    case 'fit_bounds':
      map?.fitBounds(action.bbox, { padding: mapPadding(), maxZoom: 17, duration: 1200 })
      return
    case 'add_geojson_layer':
      layers.addOverlay({
        id: action.id,
        group: 'results',
        kind: 'geojson',
        title: action.title,
        visible: true,
        opacity: 1,
        color: action.color,
        removable: true,
        data: action.geojson,
        bbox: bboxOf(action.geojson),
        featureCount: action.geojson.features.length,
        geometryTypes: [...new Set(action.geojson.features.map((f) => f.geometry?.type).filter(Boolean))] as string[],
        demo: action.kind === 'demo',
      })
      return
    case 'remove_layer':
      layers.removeOverlay(action.id)
      return
    case 'set_layer_visibility':
      layers.updateOverlay(action.id, { visible: action.visible })
      return
    case 'highlight_features':
      layers.updateOverlay(action.layer_id, { highlightIds: action.feature_ids })
      return
    case 'add_wms_layer':
      if (!isHttpUrl(action.url)) {
        console.warn('[agent] ignored WMS layer with a non-http(s) URL', action.id)
        return
      }
      layers.addOverlay({
        id: action.id,
        group: 'aerial',
        kind: 'wms',
        title: action.title,
        visible: true,
        opacity: 0.85,
        removable: true,
        attribution: action.attribution,
        wms: { url: action.url, layers: action.layers },
      })
      return
    case 'set_basemap':
      useMapStore.getState().setBasemap(action.id)
      return
    case 'set_view_mode':
      useMapStore.getState().setViewMode(action.mode)
      return
  }
}
