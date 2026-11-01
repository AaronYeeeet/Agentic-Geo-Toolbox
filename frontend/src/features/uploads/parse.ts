import { gpx, kml } from '@tmcw/togeojson'
import { bbox as turfBbox } from '@turf/turf'
import type { Feature, FeatureCollection, GeoJsonObject, Geometry, GeometryCollection, Position } from 'geojson'
import Papa from 'papaparse'
import type { BBox } from '@/store/layerStore'

/** Supported uploads: GeoJSON, CSV (auto-detected lat/lon), KML, GPX, at most 10 MB. */
export const MAX_UPLOAD_BYTES = 10 * 1024 * 1024
export const UPLOAD_ACCEPT = '.geojson,.json,.csv,.tsv,.kml,.gpx'

export type UploadFormat = 'GeoJSON' | 'CSV' | 'KML' | 'GPX'

export interface ParsedUpload {
  name: string
  format: UploadFormat
  featureCollection: FeatureCollection
  featureCount: number
  geometryTypes: string[]
  bbox: BBox
  sampleProperties: Record<string, unknown>
}

/** A failed upload with the i18n key of a user-facing explanation. */
export class UploadError extends Error {
  readonly key: string
  readonly params: Record<string, string>

  constructor(key: string, params: Record<string, string>) {
    super(key)
    this.key = key
    this.params = params
  }
}

function formatOf(name: string): UploadFormat | null {
  const extension = name.toLowerCase().split('.').pop()
  if (extension === 'geojson' || extension === 'json') return 'GeoJSON'
  if (extension === 'csv' || extension === 'tsv') return 'CSV'
  if (extension === 'kml') return 'KML'
  if (extension === 'gpx') return 'GPX'
  return null
}

const LAT = ['lat', 'latitude', 'breite', 'breitengrad', 'y', 'lat_wgs84', 'wgs84_lat', 'geo_lat', 'ycoord']
const LON = ['lon', 'lng', 'long', 'longitude', 'länge', 'laenge', 'längengrad', 'laengengrad', 'x', 'lon_wgs84', 'wgs84_lon', 'geo_lon', 'xcoord']

/** Finds the latitude and longitude columns of a CSV header (English and German names). */
export function detectLatLon(headers: string[]): { lat: string; lon: string } | null {
  const find = (names: string[]) => {
    for (const name of names) {
      const hit = headers.find((h) => h.trim().toLowerCase() === name)
      if (hit) return hit
    }
    return undefined
  }
  const lat = find(LAT)
  const lon = find(LON)
  return lat && lon ? { lat, lon } : null
}

/** Accepts "8.65", "8,65" (German decimal comma) and surrounding spaces. */
function toNumber(value: unknown): number {
  if (typeof value !== 'string') return Number.NaN
  const text = value.trim()
  return Number(/^-?\d+,\d+$/.test(text) ? text.replace(',', '.') : text)
}

function fromGeoJson(text: string): Feature[] {
  const data = JSON.parse(text) as GeoJsonObject & { features?: Feature[]; geometry?: Geometry }
  if (data.type === 'FeatureCollection') return data.features ?? []
  if (data.type === 'Feature') return [data as Feature]
  return [{ type: 'Feature', geometry: data as Geometry, properties: {} }]
}

function fromCsv(text: string, name: string): Feature[] {
  const result = Papa.parse<Record<string, string>>(text, { header: true, skipEmptyLines: true })
  const columns = detectLatLon(result.meta.fields ?? [])
  if (!columns) throw new UploadError('upload.errors.noCoordinates', { name })
  const features: Feature[] = []
  let outOfRange = 0
  for (const row of result.data) {
    const lat = toNumber(row[columns.lat])
    const lon = toNumber(row[columns.lon])
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) continue
    if (Math.abs(lat) > 90 || Math.abs(lon) > 180) {
      outOfRange += 1
      continue
    }
    const properties = Object.fromEntries(
      Object.entries(row).filter(([key]) => key !== columns.lat && key !== columns.lon),
    )
    features.push({ type: 'Feature', geometry: { type: 'Point', coordinates: [lon, lat] }, properties })
  }
  // Numbers that are all outside longitude/latitude are projected coordinates (e.g. UTM 32N).
  if (features.length === 0 && outOfRange > 0) throw new UploadError('upload.errors.projected', { name })
  return features
}

/** KML MultiGeometry becomes a GeometryCollection; keep every part as its own feature with the same properties. */
function flattenCollections(features: Feature[]): Feature[] {
  return features.flatMap((feature) =>
    feature.geometry?.type === 'GeometryCollection'
      ? flattenCollections(
          (feature.geometry as GeometryCollection).geometries.map((geometry) => ({ ...feature, geometry })),
        )
      : [feature],
  )
}

function positions(geometry: Geometry): Position[] {
  switch (geometry.type) {
    case 'Point':
      return [geometry.coordinates]
    case 'MultiPoint':
    case 'LineString':
      return geometry.coordinates
    case 'MultiLineString':
    case 'Polygon':
      return geometry.coordinates.flat()
    case 'MultiPolygon':
      return geometry.coordinates.flat(2)
    default:
      return []
  }
}

/** Reads text as UTF-8, or as Windows-1252 when it is not valid UTF-8 (German Excel saves CSV that way). */
async function readText(file: File): Promise<string> {
  const bytes = await file.arrayBuffer()
  try {
    return new TextDecoder('utf-8', { fatal: true }).decode(bytes)
  } catch {
    return new TextDecoder('windows-1252').decode(bytes)
  }
}

function fromXml(text: string, format: 'KML' | 'GPX'): Feature[] {
  const doc = new DOMParser().parseFromString(text, 'application/xml')
  if (doc.querySelector('parsererror')) throw new SyntaxError('invalid XML')
  const collection = format === 'KML' ? kml(doc) : gpx(doc)
  return collection.features as Feature[]
}

export async function parseUpload(file: File): Promise<ParsedUpload> {
  const name = file.name
  if (file.size > MAX_UPLOAD_BYTES) throw new UploadError('upload.errors.tooLarge', { name })
  const format = formatOf(name)
  if (!format) throw new UploadError('upload.errors.unsupported', { name })

  let features: Feature[]
  try {
    const text = await readText(file)
    features =
      format === 'GeoJSON' ? fromGeoJson(text) : format === 'CSV' ? fromCsv(text, name) : fromXml(text, format)
  } catch (error) {
    if (error instanceof UploadError) throw error
    throw new UploadError('upload.errors.invalid', { name, format })
  }

  features = flattenCollections(features).filter((f) => f && f.geometry && 'coordinates' in f.geometry)
  if (features.length === 0) throw new UploadError('upload.errors.empty', { name })
  const outside = features.some((f) =>
    positions(f.geometry).some(([lng, lat]) => !(Math.abs(lng) <= 180 && Math.abs(lat) <= 90)),
  )
  if (outside) throw new UploadError('upload.errors.projected', { name })

  const featureCollection: FeatureCollection = { type: 'FeatureCollection', features }
  const [west, south, east, north] = turfBbox(featureCollection)
  return {
    name,
    format,
    featureCollection,
    featureCount: features.length,
    geometryTypes: [...new Set(features.map((f) => f.geometry.type))],
    bbox: [west, south, east, north],
    sampleProperties: Object.fromEntries(Object.entries(features[0].properties ?? {}).slice(0, 8)),
  }
}
