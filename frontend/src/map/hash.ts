import type { BasemapId, ViewMode } from '@/store/mapStore'

/**
 * Shareable views: MapLibre keeps `map=zoom/lat/lng/bearing/pitch` in the hash (`hash: 'map'`);
 * we add `basemap` and `mode` next to it. The `map=` part is kept verbatim because MapLibre parses it itself.
 */
const BASEMAPS: BasemapId[] = ['osm', 'official', 'light', 'relief', 'aerial']
const MODES: ViewMode[] = ['2d', '3d']
const DEFAULTS = { basemap: 'osm', mode: '2d' } as const

export interface HashParams {
  basemap?: BasemapId
  mode?: ViewMode
}

function parts(hash: string): string[] {
  return hash.replace(/^#/, '').split('&').filter(Boolean)
}

export function readHashParams(hash: string = window.location.hash): HashParams {
  const result: HashParams = {}
  for (const part of parts(hash)) {
    const [key, value] = part.split('=')
    if (key === 'basemap' && BASEMAPS.includes(value as BasemapId)) result.basemap = value as BasemapId
    if (key === 'mode' && MODES.includes(value as ViewMode)) result.mode = value as ViewMode
  }
  return result
}

export function withHashParams(hash: string, params: Required<HashParams>): string {
  const kept = parts(hash).filter((part) => !/^(basemap|mode)=/.test(part))
  if (params.basemap !== DEFAULTS.basemap) kept.push(`basemap=${params.basemap}`)
  if (params.mode !== DEFAULTS.mode) kept.push(`mode=${params.mode}`)
  return kept.length ? `#${kept.join('&')}` : ''
}

export function writeHashParams(params: Required<HashParams>): void {
  const next = withHashParams(window.location.hash, params)
  if (next !== window.location.hash) {
    window.history.replaceState(window.history.state, '', `${window.location.pathname}${window.location.search}${next}`)
  }
}
