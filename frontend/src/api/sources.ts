import { create } from 'zustand'

/** One entry of the backend's source registry (backend/app/sources/registry.yaml, GET /api/sources). */
export interface RegistrySource {
  id: string
  title: { en: string; de: string }
  provider: string
  type: 'vector-style' | 'raster-xyz' | 'raster-dem' | 'pmtiles' | 'wms' | 'wmts' | '3dtiles' | 'geocoder' | 'api'
  url: string
  homepage?: string | null
  layers: string[]
  format?: string | null
  minzoom?: number | null
  maxzoom?: number | null
  license: { name: string; url: string }
  attribution: string
  coverage: { name: string; bbox: [number, number, number, number] }
  cors?: boolean | null
  epsg3857?: boolean | null
  usage: string
  key_required: boolean
  status: 'verified' | 'needs-proxy' | 'rejected' | 'candidate' | 'later'
  checked?: string | null
  used_for: string[]
  notes: string
}

export async function fetchSources(signal?: AbortSignal): Promise<RegistrySource[]> {
  const response = await fetch('/api/sources', { signal })
  if (!response.ok) throw new Error(`GET /api/sources failed with ${response.status}`)
  const body = (await response.json()) as { sources: RegistrySource[] }
  return body.sources
}

interface SourcesState {
  sources: RegistrySource[]
  status: 'idle' | 'loading' | 'ready' | 'error'
  load: () => Promise<void>
}

export const useSourcesStore = create<SourcesState>()((set, get) => ({
  sources: [],
  status: 'idle',
  load: async () => {
    if (get().status === 'loading' || get().status === 'ready') return
    set({ status: 'loading' })
    try {
      set({ sources: await fetchSources(), status: 'ready' })
    } catch {
      set({ status: 'error' })
    }
  },
}))

/** Verified state aerial imagery (DOP) that the browser can load directly. */
export function aerialSources(sources: RegistrySource[]): RegistrySource[] {
  return sources.filter((s) => s.status === 'verified' && s.type === 'wms' && s.used_for.includes('basemap-aerial'))
}
