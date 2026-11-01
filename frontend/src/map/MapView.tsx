import { AttributionControl, Map as MapLibreMap, ScaleControl } from 'maplibre-gl'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useSourcesStore } from '@/api/sources'
import { type ViewState, useMapStore } from '@/store/mapStore'
import { START_VIEW } from './config'
import { attachMap } from './controller'
import { attachDraw } from './draw'
import { LOD2_TILESET } from './lod2'
import { attachLod2Controller } from './lod2Controller'
import { attachPopups } from './popup'
import { readHashParams } from './hash'
import { setMap } from './mapRef'

function viewOf(map: MapLibreMap): ViewState {
  const center = map.getCenter()
  const bounds = map.getBounds()
  return {
    center: [center.lng, center.lat],
    zoom: map.getZoom(),
    bearing: map.getBearing(),
    pitch: map.getPitch(),
    bounds: [bounds.getWest(), bounds.getSouth(), bounds.getEast(), bounds.getNorth()],
  }
}

function supportsWebGL(): boolean {
  try {
    const canvas = document.createElement('canvas')
    return Boolean(canvas.getContext('webgl2') ?? canvas.getContext('webgl'))
  } catch {
    return false
  }
}

/** Creates the one MapLibre map and hands it to the rest of the app through mapRef and the stores. */
export function MapView() {
  const { t } = useTranslation()
  const container = useRef<HTMLDivElement>(null)
  const [webglOk] = useState(supportsWebGL)

  useEffect(() => {
    if (!container.current || !webglOk) return
    const fromHash = readHashParams()
    const mapStore = useMapStore.getState()
    if (fromHash.basemap) mapStore.setBasemap(fromHash.basemap)
    if (fromHash.mode) mapStore.setViewMode(fromHash.mode)
    void useSourcesStore.getState().load()

    const map = new MapLibreMap({
      container: container.current,
      // Neutral placeholder; the controller loads the chosen basemap right away (with fallbacks).
      style: { version: 8, sources: {}, layers: [{ id: 'blank', type: 'background', paint: { 'background-color': '#eef0f1' } }] },
      center: START_VIEW.center,
      zoom: START_VIEW.zoom,
      hash: 'map',
      attributionControl: false,
      maxPitch: 75,
    })

    map.addControl(new AttributionControl({ compact: window.innerWidth < 768 }), 'bottom-right')
    map.addControl(new ScaleControl({ maxWidth: 120, unit: 'metric' }), 'bottom-right')
    // Styles may name sprite images they do not ship; answer with an empty image instead of console noise.
    map.setMissingStyleImageResolver((id) => {
      if (!map.hasImage(id)) map.addImage(id, { width: 1, height: 1, data: new Uint8Array(4) })
    })
    map.on('error', (event) => {
      // Tile and source failures from public services are expected now and then; keep them visible as
      // warnings with their source instead of unhandled errors.
      const sourceId = 'sourceId' in event ? (event as { sourceId?: string }).sourceId : undefined
      console.warn('[map]', sourceId ?? '', event.error?.message ?? event)
    })
    const publishView = () => useMapStore.getState().setView(viewOf(map))
    map.on('load', publishView)
    map.on('moveend', publishView)

    const detach = attachMap(map)
    const detachDraw = attachDraw(map)
    const detachPopups = attachPopups(map)
    const detachLod2 = attachLod2Controller(map, LOD2_TILESET)
    setMap(map)
    // Hooks for Playwright (e2e tests, screenshots, the LoD2 spike); dev builds only.
    if (import.meta.env.DEV) {
      const hooks = window as unknown as { __geoMap?: MapLibreMap; __geoLod2?: (url: string) => Promise<unknown> }
      hooks.__geoMap = map
      hooks.__geoLod2 = async (url) => {
        const state = { tiles: 0, errors: [] as string[], info: null as unknown }
        ;(window as unknown as { __geoLod2State: typeof state }).__geoLod2State = state
        const { attachLod2 } = await import('./lod2')
        return attachLod2(map, url, {
          onLoad: (info) => (state.info = info),
          onTile: () => (state.tiles += 1),
          onError: (message) => state.errors.push(message),
        })
      }
    }
    return () => {
      detachLod2()
      detachPopups()
      detachDraw()
      detach()
      setMap(null)
      map.remove()
    }
  }, [webglOk])

  return (
    <>
      <div ref={container} className="absolute inset-0" data-testid="map" />
      {!webglOk && (
        <div className="absolute inset-0 grid place-items-center bg-fog p-6 text-center text-ink-2">
          <p className="max-w-sm">{t('map.noWebgl')}</p>
        </div>
      )}
    </>
  )
}
