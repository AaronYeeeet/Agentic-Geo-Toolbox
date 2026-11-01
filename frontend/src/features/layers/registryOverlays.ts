import { useEffect } from 'react'
import { type RegistrySource, useSourcesStore } from '@/api/sources'
import { type Overlay, useLayerStore } from '@/store/layerStore'

/** Registry entries with an `overlay-*` role become optional WMS layers ("Aerial and WMS" group, off by default). */
export function registryOverlays(sources: RegistrySource[]): Overlay[] {
  return sources
    .filter((s) => s.status === 'verified' && s.type === 'wms' && s.used_for.some((role) => role.startsWith('overlay-')))
    .map((s) => ({
      id: `registry-${s.id}`,
      group: 'aerial' as const,
      kind: 'wms' as const,
      title: s.title.en,
      titleI18n: s.title,
      visible: false,
      opacity: 0.85,
      removable: false,
      attribution: s.attribution,
      bbox: s.coverage.bbox,
      ...(s.minzoom != null ? { minzoom: s.minzoom } : {}),
      wms: { url: s.url, layers: s.layers, format: s.format ?? 'image/png' },
    }))
}

export function useRegistryOverlays(): void {
  const sources = useSourcesStore((s) => s.sources)
  useEffect(() => {
    const { overlays, addOverlay } = useLayerStore.getState()
    for (const overlay of registryOverlays(sources)) {
      if (!overlays.some((o) => o.id === overlay.id)) addOverlay(overlay)
    }
  }, [sources])
}
