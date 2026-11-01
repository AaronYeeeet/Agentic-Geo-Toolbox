import type { FeatureCollection } from 'geojson'
import { create } from 'zustand'

export type OverlayGroup = 'terrain' | 'buildings' | 'aerial' | 'mydata' | 'results'
export type OverlayKind = 'terrain' | 'hillshade' | 'buildings' | 'lod2' | 'wms' | 'geojson'
export type BBox = [number, number, number, number]

export interface Overlay {
  id: string
  group: OverlayGroup
  kind: OverlayKind
  /** Display title. Built-in layers use `titleKey` (i18n) instead. */
  title: string
  titleKey?: string
  /** Bilingual title from the source registry. */
  titleI18n?: { en: string; de: string }
  visible: boolean
  opacity: number
  color?: string
  attribution?: string
  removable: boolean
  data?: FeatureCollection
  bbox?: BBox
  wms?: { url: string; layers: string[]; format?: string }
  /** Zoom from which the layer draws (WMS layers that are blank below it). */
  minzoom?: number
  /** Upload metadata sent as chat context (no features are sent). */
  upload?: { format: string; sampleProperties: Record<string, unknown> }
  /** Demo data from the mock agent: hatched legend and fill. */
  demo?: boolean
  /** Feature ids (`properties.id`) emphasised by the agent. */
  highlightIds?: string[]
  /** Not usable yet (e.g. LoD2 until its tileset is verified). */
  disabled?: boolean
  featureCount?: number
  geometryTypes?: string[]
}

export const BUILT_IN_OVERLAYS: Overlay[] = [
  { id: 'terrain3d', group: 'terrain', kind: 'terrain', title: '', titleKey: 'layers.terrain3d', visible: false, opacity: 1, removable: false },
  { id: 'hillshade', group: 'terrain', kind: 'hillshade', title: '', titleKey: 'layers.hillshade', visible: false, opacity: 0.6, removable: false },
  { id: 'buildings', group: 'buildings', kind: 'buildings', title: '', titleKey: 'layers.buildings25d', visible: false, opacity: 0.9, removable: false },
  { id: 'lod2', group: 'buildings', kind: 'lod2', title: '', titleKey: 'layers.lod2', visible: false, opacity: 1, removable: false, disabled: true },
]

interface LayerState {
  overlays: Overlay[]
  addOverlay: (overlay: Overlay) => void
  updateOverlay: (id: string, patch: Partial<Overlay>) => void
  removeOverlay: (id: string) => void
}

export const useLayerStore = create<LayerState>()((set) => ({
  overlays: BUILT_IN_OVERLAYS,
  /** Adds an overlay, or replaces the one with the same id. */
  addOverlay: (overlay) =>
    set((state) => {
      const exists = state.overlays.some((o) => o.id === overlay.id)
      return {
        overlays: exists
          ? state.overlays.map((o) => (o.id === overlay.id ? overlay : o))
          : [...state.overlays, overlay],
      }
    }),
  updateOverlay: (id, patch) =>
    set((state) => ({ overlays: state.overlays.map((o) => (o.id === id ? { ...o, ...patch } : o)) })),
  removeOverlay: (id) => set((state) => ({ overlays: state.overlays.filter((o) => o.id !== id) })),
}))

export function getOverlay(id: string): Overlay | undefined {
  return useLayerStore.getState().overlays.find((o) => o.id === id)
}
