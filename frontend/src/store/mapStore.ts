import { create } from 'zustand'

export type BasemapId = 'osm' | 'official' | 'light' | 'relief' | 'aerial'
export type ViewMode = '2d' | '3d'

export interface ViewState {
  center: [number, number]
  zoom: number
  bearing: number
  pitch: number
  bounds: [number, number, number, number]
}

interface MapState {
  basemap: BasemapId
  viewMode: ViewMode
  view: ViewState | null
  /** True between a style switch and its `style.load`. */
  styleLoading: boolean
  /** True when the chosen basemap's provider is unreachable and a fallback style is shown. */
  basemapFallback: boolean
  setBasemap: (basemap: BasemapId) => void
  setViewMode: (mode: ViewMode) => void
  setView: (view: ViewState) => void
  setStyleLoading: (loading: boolean) => void
  setBasemapFallback: (fallback: boolean) => void
}

export const useMapStore = create<MapState>()((set) => ({
  basemap: 'osm',
  viewMode: '2d',
  view: null,
  styleLoading: false,
  basemapFallback: false,
  setBasemap: (basemap) => set({ basemap }),
  setViewMode: (viewMode) => set({ viewMode }),
  setView: (view) => set({ view }),
  setStyleLoading: (styleLoading) => set({ styleLoading }),
  setBasemapFallback: (basemapFallback) => set({ basemapFallback }),
}))
