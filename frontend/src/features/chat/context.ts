import type { ChatContext, UploadMeta, Viewport } from '@/api/protocol'
import { currentLanguage } from '@/i18n'
import { getMap } from '@/map/mapRef'
import { type Overlay, useLayerStore } from '@/store/layerStore'
import { useMapStore } from '@/store/mapStore'
import { useSelectionStore } from '@/store/selectionStore'

function viewport(): Viewport | undefined {
  const map = getMap()
  if (map) {
    const bounds = map.getBounds()
    const center = map.getCenter()
    return {
      bbox: [bounds.getWest(), bounds.getSouth(), bounds.getEast(), bounds.getNorth()],
      center: [center.lng, center.lat],
      zoom: map.getZoom(),
      pitch: map.getPitch(),
      bearing: map.getBearing(),
    }
  }
  const view = useMapStore.getState().view
  return view
    ? { bbox: view.bounds, center: view.center, zoom: view.zoom, pitch: view.pitch, bearing: view.bearing }
    : undefined
}

function layerKey(overlay: Overlay): string {
  const prefix =
    overlay.group === 'results' ? 'result' : overlay.group === 'mydata' ? 'upload' : overlay.kind === 'wms' ? 'wms' : 'overlay'
  return `${prefix}:${overlay.id}`
}

/** The map context sent with each question. Uploads travel as metadata only. */
export function buildChatContext(excludedUploads: string[] = []): ChatContext {
  const overlays = useLayerStore.getState().overlays
  const selection = useSelectionStore.getState().selection
  const uploads: UploadMeta[] = overlays
    .filter((o) => o.group === 'mydata' && !excludedUploads.includes(o.id))
    .map((o) => ({
      id: o.id,
      name: o.title,
      feature_count: o.featureCount ?? 0,
      bbox: o.bbox ?? [],
      geometry_types: o.geometryTypes ?? [],
      sample_properties: o.upload?.sampleProperties ?? {},
    }))
  return {
    ui_language: currentLanguage(),
    viewport: viewport(),
    ...(selection ? { selection } : {}),
    active_layers: [
      `basemap:${useMapStore.getState().basemap}`,
      ...overlays.filter((o) => o.visible && !o.disabled).map(layerKey),
    ],
    uploads,
  }
}
