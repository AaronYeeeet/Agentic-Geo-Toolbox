import type { Map as MapLibreMap } from 'maplibre-gl'
import { useSyncExternalStore } from 'react'

/** The one MapLibre map of the app, shared outside React (map actions, stores) and inside (hooks). */
let current: MapLibreMap | null = null
const listeners = new Set<() => void>()

export function setMap(map: MapLibreMap | null): void {
  current = map
  listeners.forEach((listener) => listener())
}

export function getMap(): MapLibreMap | null {
  return current
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function useMap(): MapLibreMap | null {
  return useSyncExternalStore(subscribe, getMap, () => null)
}
