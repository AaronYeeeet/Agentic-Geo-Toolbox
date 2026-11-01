import type { StyleSpecification } from '@maplibre/maplibre-gl-style-spec'
import type { RegistrySource } from '@/api/sources'
import type { BasemapId } from '@/store/mapStore'
import { BASEMAPS, buildAerialStyle } from './basemaps'

const STYLE_TIMEOUT_MS = 5000
const OPENFREEMAP = 'https://tiles.openfreemap.org/styles'

/**
 * basemap.de (BKG) was unreachable when last checked (2026-11-01). When a basemap.de style does not
 * load in time, these OpenFreeMap styles stand in, and the UI says so.
 */
const FALLBACKS: Partial<Record<BasemapId, string>> = {
  official: `${OPENFREEMAP}/bright`,
  light: `${OPENFREEMAP}/positron`,
  relief: `${OPENFREEMAP}/positron`,
}

/** Style URLs that failed in this session; we do not wait for them again. */
const unreachable = new Set<string>()

export function resetStyleCache(): void {
  unreachable.clear()
}

async function fetchStyle(url: string): Promise<StyleSpecification> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), STYLE_TIMEOUT_MS)
  try {
    const response = await fetch(url, { signal: controller.signal })
    if (!response.ok) throw new Error(`${url}: HTTP ${response.status}`)
    return (await response.json()) as StyleSpecification
  } finally {
    clearTimeout(timer)
  }
}

/** Replace `["get", "ref_length"]` in numeric comparisons with a null-safe version (same result, no warning). */
function guardRefLength(node: unknown): unknown {
  if (!Array.isArray(node)) return node
  if (['<', '<=', '>', '>='].includes(node[0] as string)) {
    return node.map((part) =>
      Array.isArray(part) && part[0] === 'get' && part[1] === 'ref_length' ? ['coalesce', part, 99] : guardRefLength(part),
    )
  }
  return node.map(guardRefLength)
}

/**
 * Small fixes for third-party styles under MapLibre v6. OpenFreeMap's shield layers compare `ref_length` with a
 * number although many roads have none, which v6 reports as a warning for every such layer.
 */
export function patchStyle(style: StyleSpecification): StyleSpecification {
  return {
    ...style,
    layers: style.layers.map((layer) =>
      'filter' in layer && layer.filter ? ({ ...layer, filter: guardRefLength(layer.filter) } as typeof layer) : layer,
    ),
  }
}

export interface LoadedStyle {
  style: StyleSpecification
  /** True when a fallback style stands in for an unreachable provider. */
  fallback: boolean
}

export async function loadBasemapStyle(id: BasemapId, registry: RegistrySource[]): Promise<LoadedStyle> {
  if (id === 'aerial') return { style: buildAerialStyle(registry), fallback: false }
  const url = BASEMAPS.find((b) => b.id === id)?.style ?? `${OPENFREEMAP}/liberty`
  if (!unreachable.has(url)) {
    try {
      return { style: patchStyle(await fetchStyle(url)), fallback: false }
    } catch (error) {
      unreachable.add(url)
      console.warn('[basemap] style unavailable, using fallback:', url, String(error))
    }
  }
  const fallback = FALLBACKS[id]
  if (!fallback) throw new Error(`basemap ${id} unavailable`)
  return { style: patchStyle(await fetchStyle(fallback)), fallback: true }
}
