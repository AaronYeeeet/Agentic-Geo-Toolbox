import { area as turfArea, bboxPolygon } from '@turf/turf'
import type { BBox } from '@/store/layerStore'
import type { SelectionFeature } from '@/store/selectionStore'

/**
 * Photon (komoot) search-as-you-type, verified 2026-11-01: `lang` accepts only default/de/en/fr, `extent` is
 * [west, north, east, south]. Fair use: callers debounce, wait for 3 characters and cancel stale requests.
 */
const PHOTON_URL = 'https://photon.komoot.io/api/'

export interface SearchResult {
  id: string
  name: string
  detail: string
  center: [number, number]
  bbox?: BBox
  countryCode?: string
  kind: string
}

interface PhotonProperties {
  name?: string
  street?: string
  housenumber?: string
  postcode?: string
  city?: string
  town?: string
  village?: string
  district?: string
  county?: string
  state?: string
  country?: string
  countrycode?: string
  osm_id?: number
  osm_type?: string
  osm_key?: string
  osm_value?: string
  type?: string
  extent?: [number, number, number, number]
}

interface PhotonFeature {
  geometry: { coordinates: [number, number] }
  properties: PhotonProperties
}

function toResult(feature: PhotonFeature, index: number): SearchResult {
  const p = feature.properties
  const address = [p.street, p.housenumber].filter(Boolean).join(' ')
  const name = p.name ?? (address || p.city || p.town || p.village || '?')
  const place = p.city ?? p.town ?? p.village ?? p.district ?? p.county
  const detail = [
    address && address !== name ? address : null,
    place && place !== name ? place : null,
    p.state && p.state !== name ? p.state : null,
    p.countrycode !== 'DE' ? p.country : null,
  ]
    .filter(Boolean)
    .join(', ')
  const e = p.extent
  return {
    id: p.osm_type && p.osm_id ? `${p.osm_type}${p.osm_id}` : `r${index}`,
    name,
    detail,
    center: feature.geometry.coordinates,
    ...(e ? { bbox: [e[0], e[3], e[2], e[1]] as BBox } : {}),
    countryCode: p.countrycode,
    kind: p.osm_value ?? p.type ?? 'place',
  }
}

export async function searchPhoton(
  query: string,
  options: { lang: 'en' | 'de'; center: [number, number]; zoom: number; signal?: AbortSignal; limit?: number },
): Promise<SearchResult[]> {
  const limit = options.limit ?? 7
  const params = new URLSearchParams({
    q: query,
    lang: options.lang,
    limit: String(limit + 3),
    lat: options.center[1].toFixed(5),
    lon: options.center[0].toFixed(5),
    zoom: String(Math.max(1, Math.round(options.zoom))),
  })
  const response = await fetch(`${PHOTON_URL}?${params.toString()}`, { signal: options.signal })
  if (!response.ok) throw new Error(`Photon answered ${response.status}`)
  const body = (await response.json()) as { features: PhotonFeature[] }
  const seen = new Set<string>()
  const results = body.features.map(toResult).filter((r) => {
    const key = `${r.name}|${r.detail}`
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
  // Germany-wide tool: results in Germany first, Photon's own order otherwise (the sort is stable).
  results.sort((a, b) => Number(b.countryCode === 'DE') - Number(a.countryCode === 'DE'))
  return results.slice(0, limit)
}

/** Search result as selection: its extent, or a 200 m box around a point (boundaries are not used yet). */
export function selectionFromResult(result: SearchResult): SelectionFeature {
  let bbox = result.bbox
  if (!bbox) {
    const [lng, lat] = result.center
    const dLat = 100 / 111_320
    const dLng = 100 / (111_320 * Math.cos((lat * Math.PI) / 180))
    bbox = [lng - dLng, lat - dLat, lng + dLng, lat + dLat]
  }
  const polygon = bboxPolygon(bbox)
  return {
    type: 'Feature',
    geometry: polygon.geometry,
    properties: { kind: 'search', area_m2: turfArea(polygon), label: result.name },
  }
}
