import type { Map as MapLibreMap } from 'maplibre-gl'
import { type Overlay, useLayerStore } from '@/store/layerStore'
import { type ViewMode, useMapStore } from '@/store/mapStore'
import type { Lod2Handle } from './lod2'

/** LoD2 is shown only when its toggle is enabled and on, in the 3D view. */
export function shouldShowLod2(overlays: Overlay[], viewMode: ViewMode): boolean {
  const lod2 = overlays.find((o) => o.id === 'lod2')
  return Boolean(lod2 && !lod2.disabled && lod2.visible && viewMode === '3d')
}

/**
 * Drives the LoD2 overlay from the stores. While it is shown, the 2.5D extrusions (same buildings twice) and the
 * terrain (the height-zero tileset would float or sink) are switched off and restored afterwards.
 */
export function attachLod2Controller(map: MapLibreMap, url: string): () => void {
  let handle: Lod2Handle | null = null
  let pending = false
  let restore: { buildings: boolean; terrain: boolean } | null = null

  const sync = async () => {
    const { overlays, updateOverlay } = useLayerStore.getState()
    const show = shouldShowLod2(overlays, useMapStore.getState().viewMode)
    if (show && !handle && !pending) {
      pending = true
      const visible = (id: string) => overlays.find((o) => o.id === id)?.visible ?? false
      restore = { buildings: visible('buildings'), terrain: visible('terrain3d') }
      updateOverlay('buildings', { visible: false })
      updateOverlay('terrain3d', { visible: false })
      const { attachLod2 } = await import('./lod2')
      handle = await attachLod2(map, url)
      pending = false
    } else if (!show && handle) {
      handle.remove()
      handle = null
      if (restore) {
        updateOverlay('buildings', { visible: restore.buildings })
        updateOverlay('terrain3d', { visible: restore.terrain })
        restore = null
      }
    }
    const lod2 = useLayerStore.getState().overlays.find((o) => o.id === 'lod2')
    if (handle && lod2) handle.setOpacity(lod2.opacity)
  }

  // A style switch drops deck.gl's interleaved layer; attach it again.
  const onStyle = () => {
    if (!handle) return
    handle.remove()
    handle = null
    void sync()
  }
  map.on('style.load', onStyle)
  const unsubscribers = [useLayerStore.subscribe(() => void sync()), useMapStore.subscribe(() => void sync())]
  return () => {
    map.off('style.load', onStyle)
    unsubscribers.forEach((unsubscribe) => unsubscribe())
    handle?.remove()
  }
}
