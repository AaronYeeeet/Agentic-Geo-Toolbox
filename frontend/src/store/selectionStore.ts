import type { Feature, MultiPolygon, Point, Polygon } from 'geojson'
import { create } from 'zustand'

export type SelectionKind = 'rectangle' | 'polygon' | 'feature' | 'view' | 'search'

export type SelectionFeature = Feature<
  Polygon | MultiPolygon | Point,
  { kind: SelectionKind; area_m2: number; label?: string }
>

interface SelectionState {
  /** The one active selection (a single selection for now). */
  selection: SelectionFeature | null
  setSelection: (selection: SelectionFeature) => void
  clearSelection: () => void
}

export const useSelectionStore = create<SelectionState>()((set) => ({
  selection: null,
  setSelection: (selection) => set({ selection }),
  clearSelection: () => set({ selection: null }),
}))
