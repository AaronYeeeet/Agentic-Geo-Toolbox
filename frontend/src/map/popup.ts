import type { Map as MapLibreMap, MapMouseEvent } from 'maplibre-gl'
import { Popup } from 'maplibre-gl'
import i18n from '@/i18n'
import { useDrawStore } from '@/store/drawStore'
import { useLayerStore } from '@/store/layerStore'

const MAX_ROWS = 24
const NAME_KEYS = ['name', 'title', 'titel', 'bezeichnung', 'label']

function el<K extends keyof HTMLElementTagNameMap>(tag: K, className: string, text?: string) {
  const node = document.createElement(tag)
  node.className = className
  if (text !== undefined) node.textContent = text
  return node
}

function display(value: unknown): string {
  if (value === null || value === undefined) return '–'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

/** Popup body built from DOM nodes and textContent only: uploaded data can never inject markup. */
export function popupContent(layerTitle: string, properties: Record<string, unknown>): HTMLElement {
  const root = el('div', 'gt-popup')
  const nameKey = Object.keys(properties).find((key) => NAME_KEYS.includes(key.toLowerCase()))
  const name = nameKey ? properties[nameKey] : undefined
  root.append(el('h3', 'gt-popup-title', typeof name === 'string' && name ? name : layerTitle))
  root.append(el('p', 'gt-popup-layer', layerTitle))
  const entries = Object.entries(properties).slice(0, MAX_ROWS)
  if (entries.length === 0) {
    root.append(el('p', 'gt-popup-empty', i18n.t('map.popupEmpty')))
    return root
  }
  const table = el('table', 'gt-popup-table')
  for (const [key, value] of entries) {
    const row = el('tr', '')
    row.append(el('th', '', key), el('td', '', display(value)))
    table.append(row)
  }
  root.append(table)
  return root
}

const isFeatureLayer = (id: string) => id.startsWith('gt-geojson-') && !id.includes('-highlight-')

/** Feature info: clicking a feature of an upload or an agent result shows its properties. */
export function attachPopups(map: MapLibreMap): () => void {
  const popup = new Popup({ closeButton: true, maxWidth: '320px', offset: 10 })

  const hit = (event: MapMouseEvent) => {
    const layers = map.getLayersOrder().filter(isFeatureLayer)
    return layers.length ? map.queryRenderedFeatures(event.point, { layers })[0] : undefined
  }

  const onClick = (event: MapMouseEvent) => {
    if (useDrawStore.getState().tool) return
    const feature = hit(event)
    if (!feature) return
    const overlayId = feature.layer.id.replace(/^gt-geojson-/, '').replace(/-(fill|line|circle)$/, '')
    const overlay = useLayerStore.getState().overlays.find((o) => o.id === overlayId)
    popup
      .setLngLat(event.lngLat)
      .setDOMContent(popupContent(overlay?.title ?? '', feature.properties ?? {}))
      .addTo(map)
  }

  const onMove = (event: MapMouseEvent) => {
    if (useDrawStore.getState().tool) return
    map.getCanvas().style.cursor = hit(event) ? 'pointer' : ''
  }

  map.on('click', onClick)
  map.on('mousemove', onMove)
  return () => {
    map.off('click', onClick)
    map.off('mousemove', onMove)
    popup.remove()
  }
}
