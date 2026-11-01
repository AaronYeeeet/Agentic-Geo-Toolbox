import type { LayerSpecification, SourceSpecification, StyleSpecification } from '@maplibre/maplibre-gl-style-spec'
import { type RegistrySource, aerialSources } from '@/api/sources'
import { escapeHtml, isHttpUrl } from '@/lib/safe'
import { wmsTileUrl } from '@/lib/wms'
import type { BasemapId } from '@/store/mapStore'

export interface BasemapDef {
  id: BasemapId
  /** Style URL; the aerial basemap is built from the source registry instead. */
  style?: string
}

const BKG = 'https://sgx.geodatenzentrum.de/gdz_basemapde_vektor/styles'

/** Basemaps: OSM (default), Official, Light, Relief, Aerial. Sources: backend/app/sources/registry.yaml. */
export const BASEMAPS: BasemapDef[] = [
  { id: 'osm', style: 'https://tiles.openfreemap.org/styles/liberty' },
  { id: 'official', style: `${BKG}/bm_web_col.json` },
  { id: 'light', style: `${BKG}/bm_web_gry.json` },
  { id: 'relief', style: `${BKG}/bm_web_top.json` },
  { id: 'aerial' },
]

const OPENFREEMAP_GLYPHS = 'https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf'

function link(text: string, url?: string | null) {
  const safe = escapeHtml(text)
  return url && isHttpUrl(url) ? `<a href="${escapeHtml(url)}" target="_blank" rel="noopener">${safe}</a>` : safe
}

/**
 * Aerial basemap: every verified state DOP WMS as its own raster source, clipped to its coverage bounds and
 * requested as transparent PNG so neighbouring states never paint over each other. EOX Sentinel-2 cloudless sits
 * underneath as a coarse fallback; OpenFreeMap place labels on top keep the photo readable.
 */
export function buildAerialStyle(registry: RegistrySource[]): StyleSpecification {
  const sources: Record<string, SourceSpecification> = {}
  const layers: LayerSpecification[] = [
    { id: 'aerial-background', type: 'background', paint: { 'background-color': '#2b3236' } },
  ]

  const fallback = registry.find(
    (s) => s.status === 'verified' && s.type === 'raster-xyz' && s.used_for.includes('basemap-aerial'),
  )
  if (fallback) {
    sources['aerial-fallback'] = {
      type: 'raster',
      tiles: [fallback.url],
      tileSize: 256,
      maxzoom: fallback.maxzoom ?? 14,
      attribution: link(fallback.attribution, fallback.homepage ?? fallback.license.url),
    }
    layers.push({ id: 'aerial-fallback', type: 'raster', source: 'aerial-fallback' })
  }

  for (const source of aerialSources(registry)) {
    const id = `aerial-${source.id}`
    sources[id] = {
      type: 'raster',
      tiles: [wmsTileUrl(source.url, source.layers, { format: 'image/png', transparent: true })],
      tileSize: 256,
      bounds: source.coverage.bbox,
      ...(source.minzoom != null ? { minzoom: source.minzoom } : {}),
      maxzoom: source.maxzoom ?? 20,
      attribution: link(source.attribution, source.homepage ?? source.license.url),
    }
    layers.push({ id, type: 'raster', source: id, ...(source.minzoom != null ? { minzoom: source.minzoom } : {}) })
  }

  sources['labels'] = { type: 'vector', url: 'https://tiles.openfreemap.org/planet' }
  layers.push(
    {
      id: 'aerial-road-labels',
      type: 'symbol',
      source: 'labels',
      'source-layer': 'transportation_name',
      minzoom: 14,
      layout: {
        'symbol-placement': 'line',
        'text-field': ['get', 'name'],
        'text-font': ['Noto Sans Regular'],
        'text-size': 12,
      },
      paint: { 'text-color': '#ffffff', 'text-halo-color': 'rgba(0,0,0,0.75)', 'text-halo-width': 1.2 },
    },
    {
      id: 'aerial-place-labels',
      type: 'symbol',
      source: 'labels',
      'source-layer': 'place',
      filter: ['match', ['get', 'class'], ['city', 'town', 'village', 'suburb', 'quarter'], true, false],
      layout: {
        'text-field': ['get', 'name'],
        'text-font': ['Noto Sans Bold'],
        'text-size': ['match', ['get', 'class'], 'city', 18, 'town', 15, 13],
        'text-max-width': 8,
      },
      paint: { 'text-color': '#ffffff', 'text-halo-color': 'rgba(0,0,0,0.75)', 'text-halo-width': 1.4 },
    },
  )

  return { version: 8, glyphs: OPENFREEMAP_GLYPHS, sources, layers }
}

/** Is a point inside any verified aerial coverage? Coverage is a bounding box, so this is an approximation. */
export function aerialCoverageAt(registry: RegistrySource[], lng: number, lat: number): RegistrySource[] {
  return aerialSources(registry).filter(({ coverage: { bbox } }) => lng >= bbox[0] && lng <= bbox[2] && lat >= bbox[1] && lat <= bbox[3])
}

