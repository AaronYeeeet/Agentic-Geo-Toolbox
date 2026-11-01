import type { PaddingOptions } from 'maplibre-gl'
import type { BBox } from '@/store/layerStore'
import { getMap } from './mapRef'

/** Room for the floating panels, plus the bottom sheet on phones. */
export function mapPadding(): PaddingOptions {
  const sheet = Number.parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--sheet-offset')) || 0
  return { top: 90, right: 70, bottom: 70 + sheet, left: 90 }
}

const isLngLatBox = ([west, south, east, north]: BBox) =>
  [west, south, east, north].every(Number.isFinite) &&
  Math.abs(west) <= 180 &&
  Math.abs(east) <= 180 &&
  Math.abs(south) <= 90 &&
  Math.abs(north) <= 90

/**
 * The one way to zoom to a box: checks that it is longitude/latitude (MapLibre throws otherwise) and keeps the
 * panels and the bottom sheet out of the way. Returns whether the map moved.
 */
export function fitToBBox(bbox: BBox, maxZoom = 17): boolean {
  const map = getMap()
  if (!map || !isLngLatBox(bbox)) return false
  map.fitBounds(bbox, { padding: mapPadding(), maxZoom, duration: 1000 })
  return true
}
