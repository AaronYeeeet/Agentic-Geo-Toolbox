import type { Map as MapLibreMap } from 'maplibre-gl'
import { useSourcesStore } from '@/api/sources'
import { useLayerStore } from '@/store/layerStore'
import { type BasemapId, type ViewMode, useMapStore } from '@/store/mapStore'
import { useSelectionStore } from '@/store/selectionStore'
import { writeHashParams } from './hash'
import { reconcileOverlays } from './overlays'
import { loadBasemapStyle } from './styles'

/** 3D means pitch about 60°, terrain on, extrusions on; 2D is top-down without terrain. */
export const PITCH_3D = 60

function setViewModeOverlays(mode: ViewMode) {
  const { updateOverlay } = useLayerStore.getState()
  updateOverlay('terrain3d', { visible: mode === '3d' })
  updateOverlay('buildings', { visible: mode === '3d' })
}

function writeHash() {
  const { basemap, viewMode } = useMapStore.getState()
  writeHashParams({ basemap, mode: viewMode })
}

/**
 * Connects the stores to one map instance: overlay reconciliation after each style load and store change,
 * basemap switching, the 2D/3D mode, and the shareable hash. Returns a cleanup function.
 */
export function attachMap(map: MapLibreMap): () => void {
  let styleReady = false
  let request = 0
  let detached = false
  // Hillshade switched on by us because the Relief basemap fell back to a style without relief.
  let autoHillshade = false

  const sync = () => {
    if (!styleReady) return
    reconcileOverlays(map, {
      overlays: useLayerStore.getState().overlays,
      selection: useSelectionStore.getState().selection,
    })
  }

  const setAutoHillshade = (on: boolean) => {
    const { updateOverlay, overlays } = useLayerStore.getState()
    const hillshade = overlays.find((o) => o.id === 'hillshade')
    if (on && hillshade && !hillshade.visible) {
      autoHillshade = true
      updateOverlay('hillshade', { visible: true })
    } else if (!on && autoHillshade) {
      autoHillshade = false
      updateOverlay('hillshade', { visible: false })
    }
  }

  const switchBasemap = async (id: BasemapId) => {
    const ticket = ++request
    useMapStore.getState().setStyleLoading(true)
    try {
      const { style, fallback } = await loadBasemapStyle(id, useSourcesStore.getState().sources)
      if (detached || ticket !== request) return
      styleReady = false
      map.setStyle(style, { diff: false })
      useMapStore.getState().setBasemapFallback(fallback)
      setAutoHillshade(id === 'relief' && fallback)
    } catch (error) {
      if (detached || ticket !== request) return
      console.warn('[basemap] could not load', id, String(error))
      useMapStore.getState().setStyleLoading(false)
      if (id !== 'osm') useMapStore.getState().setBasemap('osm')
    }
  }

  const applyViewMode = (mode: ViewMode, animate = true) => {
    setViewModeOverlays(mode)
    const camera = mode === '3d' ? { pitch: PITCH_3D } : { pitch: 0, bearing: 0 }
    if (animate) map.easeTo({ ...camera, duration: 900 })
    else map.jumpTo(camera)
  }

  const onStyleLoad = () => {
    styleReady = true
    useMapStore.getState().setStyleLoading(false)
    sync()
  }
  map.on('style.load', onStyleLoad)

  const unsubscribers = [
    useLayerStore.subscribe(sync),
    useSelectionStore.subscribe(sync),
    useMapStore.subscribe((state, previous) => {
      if (state.basemap !== previous.basemap) void switchBasemap(state.basemap)
      if (state.viewMode !== previous.viewMode) applyViewMode(state.viewMode)
      if (state.basemap !== previous.basemap || state.viewMode !== previous.viewMode) writeHash()
    }),
    // The aerial basemap is built from the registry; rebuild it once the registry has arrived.
    useSourcesStore.subscribe((state, previous) => {
      if (state.status === 'ready' && previous.status !== 'ready' && useMapStore.getState().basemap === 'aerial') {
        void switchBasemap('aerial')
      }
    }),
  ]

  if (useMapStore.getState().viewMode === '3d') applyViewMode('3d', false)
  void switchBasemap(useMapStore.getState().basemap)

  return () => {
    detached = true
    map.off('style.load', onStyleLoad)
    unsubscribers.forEach((unsubscribe) => unsubscribe())
  }
}
