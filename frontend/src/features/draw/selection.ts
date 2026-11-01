import { area as turfArea, bboxPolygon, unkinkPolygon } from '@turf/turf'
import type { Feature, Geometry, MultiPolygon, Polygon } from 'geojson'
import type { BBox } from '@/store/layerStore'
import type { SelectionFeature, SelectionKind } from '@/store/selectionStore'

/** Area of a polygon that may cross itself: a bowtie's lobes would otherwise cancel each other out. */
function polygonArea(feature: Feature<Polygon | MultiPolygon>): number {
  try {
    return unkinkPolygon(feature).features.reduce((sum, part) => sum + turfArea(part), 0)
  } catch {
    return turfArea(feature)
  }
}

/** A drawn rectangle or polygon as the selection, with its geodesic area. */
export function selectionFromDrawing(feature: Feature, kind: Extract<SelectionKind, 'rectangle' | 'polygon'>): SelectionFeature | null {
  if (feature.geometry?.type !== 'Polygon') return null
  return { type: 'Feature', geometry: feature.geometry, properties: { kind, area_m2: polygonArea(feature as Feature<Polygon>) } }
}

function labelOf(properties: Record<string, unknown> | null): string | undefined {
  const value = properties?.name ?? properties?.['name:de'] ?? properties?.title ?? properties?.class
  return typeof value === 'string' ? value : undefined
}

/** A clicked building, place or result feature as the selection. Lines are not areas, so they are skipped. */
export function selectionFromFeature(feature: Feature<Geometry | null>): SelectionFeature | null {
  const geometry = feature.geometry
  const label = labelOf(feature.properties)
  if (!geometry) return null
  if (geometry.type === 'Polygon' || geometry.type === 'MultiPolygon') {
    return {
      type: 'Feature',
      geometry,
      properties: {
        kind: 'feature',
        area_m2: polygonArea(feature as Feature<Polygon | MultiPolygon>),
        ...(label ? { label } : {}),
      },
    }
  }
  if (geometry.type === 'Point') {
    return { type: 'Feature', geometry, properties: { kind: 'feature', area_m2: 0, ...(label ? { label } : {}) } }
  }
  return null
}

/** The visible map area as the selection ("use current view"). */
export function selectionFromBounds(bounds: BBox): SelectionFeature {
  const polygon = bboxPolygon(bounds)
  return { type: 'Feature', geometry: polygon.geometry, properties: { kind: 'view', area_m2: turfArea(polygon) } }
}
