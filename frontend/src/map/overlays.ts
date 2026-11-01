/**
 * Store-to-map reconciliation. The Zustand stores are the source of truth for every overlay; this module makes the
 * MapLibre style match them. It is idempotent and runs after every style load (a basemap switch drops all custom
 * sources and layers) and after every store change.
 */
import type {
  AllPaintProperties,
  ExpressionSpecification,
  FilterSpecification,
  LayerSpecification,
  SkySpecification,
  SourceSpecification,
  TerrainSpecification,
} from '@maplibre/maplibre-gl-style-spec'
import type { GeoJSON } from 'geojson'
import type { GeoJSONSource, Map as MapLibreMap } from 'maplibre-gl'
import { escapeHtml } from '@/lib/safe'
import { wmsTileUrl } from '@/lib/wms'
import type { Overlay } from '@/store/layerStore'
import type { SelectionFeature } from '@/store/selectionStore'
import { DEM_SOURCE, OPENFREEMAP_SOURCE, OVERPRINT, SKY, TERRAIN_EXAGGERATION } from './config'

export type MapLike = Pick<
  MapLibreMap,
  | 'getLayersOrder'
  | 'getLayer'
  | 'addLayer'
  | 'moveLayer'
  | 'removeLayer'
  | 'getSource'
  | 'addSource'
  | 'removeSource'
  | 'setLayoutProperty'
  | 'setPaintProperty'
  | 'setFilter'
  | 'setTerrain'
  | 'getTerrain'
  | 'setSky'
  | 'getSky'
  | 'hasImage'
  | 'addImage'
>

export interface OverlayRenderState {
  overlays: Overlay[]
  selection: SelectionFeature | null
}

/** Every source and layer this app adds starts with this prefix; anything else belongs to the basemap. */
export const PREFIX = 'gt-'
export const SELECTION_SOURCE = 'gt-selection'
export const TERRAIN_SOURCE = 'gt-dem-terrain'
export const BUILDINGS_LAYER = 'gt-buildings'
export const geojsonSourceId = (overlayId: string) => `gt-geojson-${overlayId}`
export const geojsonLayerIds = (overlayId: string) =>
  ['fill', 'line', 'circle'].map((suffix) => `${geojsonSourceId(overlayId)}-${suffix}`)

type Placement = 'below-lines' | 'below-labels' | 'top'

interface DesiredLayer {
  spec: LayerSpecification
  placement: Placement
  visible: boolean
}

interface DesiredSource {
  id: string
  spec: SourceSpecification
  data?: unknown
}

interface StyleImage {
  width: number
  height: number
  data: Uint8Array
}

interface Desired {
  sources: DesiredSource[]
  layers: DesiredLayer[]
  images: { id: string; image: StyleImage }[]
  terrain: TerrainSpecification | null
  sky: SkySpecification
  hideBasemapExtrusions: boolean
}

const POLYGON: FilterSpecification = ['match', ['geometry-type'], ['Polygon', 'MultiPolygon'], true, false]
const LINEAR: FilterSpecification = [
  'match',
  ['geometry-type'],
  ['LineString', 'MultiLineString', 'Polygon', 'MultiPolygon'],
  true,
  false,
]
const POINT: FilterSpecification = ['match', ['geometry-type'], ['Point', 'MultiPoint'], true, false]
const EMPTY: GeoJSON = { type: 'FeatureCollection', features: [] }

// --- builders -------------------------------------------------------------------------------------

function hexToRgb(hex: string): [number, number, number] {
  const value = hex.replace('#', '')
  const full = value.length === 3 ? [...value].map((c) => c + c).join('') : value
  const n = Number.parseInt(full, 16)
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}

/** Diagonal hatch in the layer colour: the map-side twin of the hatched legend swatch for demo data. */
export function hatchImage(hex: string): StyleImage {
  const [r, g, b] = hexToRgb(hex)
  const size = 12
  const data = new Uint8Array(size * size * 4)
  for (let y = 0; y < size; y += 1) {
    for (let x = 0; x < size; x += 1) {
      const i = (y * size + x) * 4
      const stripe = (x + y) % 6 < 2
      data.set([r, g, b, stripe ? 210 : 46], i)
    }
  }
  return { width: size, height: size, data }
}

const hatchId = (hex: string) => `gt-hatch-${hex.replace('#', '').toLowerCase()}`

function geojsonOverlay(o: Overlay, want: Desired) {
  const source = geojsonSourceId(o.id)
  const color = o.color ?? '#1f5f8b'
  const opacity = o.opacity
  const ids = o.highlightIds ?? []
  const byId: ExpressionSpecification = ['in', ['to-string', ['get', 'id']], ['literal', ids]]
  const data = o.data ?? EMPTY
  want.sources.push({ id: source, spec: { type: 'geojson', data }, data })

  let fillPaint: Record<string, unknown> = { 'fill-color': color, 'fill-opacity': 0.24 * opacity }
  if (o.demo) {
    const image = hatchId(color)
    want.images.push({ id: image, image: hatchImage(color) })
    fillPaint = { 'fill-pattern': image, 'fill-opacity': 0.85 * opacity }
  }
  const layer = (spec: Record<string, unknown>, visible = o.visible): DesiredLayer => ({
    spec: { source, ...spec } as LayerSpecification,
    placement: 'below-labels',
    visible,
  })
  want.layers.push(
    layer({ id: `${source}-fill`, type: 'fill', filter: POLYGON, paint: fillPaint }),
    layer({
      id: `${source}-line`,
      type: 'line',
      filter: LINEAR,
      layout: { 'line-join': 'round', 'line-cap': 'round' },
      paint: { 'line-color': color, 'line-width': 2, 'line-opacity': opacity },
    }),
    layer({
      id: `${source}-circle`,
      type: 'circle',
      filter: POINT,
      paint: {
        'circle-radius': ['interpolate', ['linear'], ['zoom'], 10, 4, 16, 7],
        'circle-color': color,
        'circle-opacity': opacity,
        'circle-stroke-color': '#ffffff',
        'circle-stroke-width': 2,
        'circle-stroke-opacity': opacity,
      },
    }),
    layer(
      {
        id: `${source}-highlight-line`,
        type: 'line',
        filter: ['all', LINEAR, byId],
        layout: { 'line-join': 'round' },
        paint: { 'line-color': OVERPRINT, 'line-width': 4, 'line-opacity': opacity },
      },
      o.visible && ids.length > 0,
    ),
    layer(
      {
        id: `${source}-highlight-circle`,
        type: 'circle',
        filter: ['all', POINT, byId],
        paint: {
          'circle-radius': ['interpolate', ['linear'], ['zoom'], 10, 8, 16, 12],
          'circle-color': 'rgba(0,0,0,0)',
          'circle-stroke-color': OVERPRINT,
          'circle-stroke-width': 3,
          'circle-stroke-opacity': opacity,
        },
      },
      o.visible && ids.length > 0,
    ),
  )
}

function wmsOverlay(o: Overlay, want: Desired) {
  if (!o.wms) return
  const id = `gt-wms-${o.id}`
  want.sources.push({
    id,
    spec: {
      type: 'raster',
      tiles: [wmsTileUrl(o.wms.url, o.wms.layers, { format: o.wms.format ?? 'image/png' })],
      tileSize: 256,
      // MapLibre renders attributions as HTML; agent-provided text must stay text.
      ...(o.attribution ? { attribution: escapeHtml(o.attribution) } : {}),
      ...(o.bbox ? { bounds: o.bbox } : {}),
      ...(o.minzoom != null ? { minzoom: o.minzoom } : {}),
    },
  })
  want.layers.push({
    spec: {
      id,
      type: 'raster',
      source: id,
      ...(o.minzoom != null ? { minzoom: o.minzoom } : {}),
      paint: { 'raster-opacity': o.opacity },
    },
    placement: 'below-labels',
    visible: o.visible,
  })
}

function hillshadeOverlay(o: Overlay, want: Desired) {
  want.sources.push({ id: 'gt-dem-hillshade', spec: DEM_SOURCE })
  want.layers.push({
    spec: {
      id: 'gt-hillshade',
      type: 'hillshade',
      source: 'gt-dem-hillshade',
      paint: {
        'hillshade-method': 'igor',
        'hillshade-exaggeration': 0.9 * o.opacity,
        'hillshade-shadow-color': `rgba(32, 45, 58, ${0.7 * o.opacity})`,
        'hillshade-highlight-color': `rgba(255, 255, 255, ${0.35 * o.opacity})`,
        'hillshade-accent-color': `rgba(32, 45, 58, ${0.25 * o.opacity})`,
      },
    } as LayerSpecification,
    placement: 'below-lines',
    visible: o.visible,
  })
}

function buildingsOverlay(o: Overlay, want: Desired) {
  want.sources.push({ id: 'gt-ofm', spec: OPENFREEMAP_SOURCE })
  const height: ExpressionSpecification = ['coalesce', ['get', 'render_height'], 5]
  want.layers.push({
    spec: {
      id: BUILDINGS_LAYER,
      type: 'fill-extrusion',
      source: 'gt-ofm',
      'source-layer': 'building',
      minzoom: 14,
      filter: ['!=', ['get', 'hide_3d'], true],
      paint: {
        'fill-extrusion-color': ['interpolate', ['linear'], height, 0, '#e7e4de', 25, '#d9d5cd', 80, '#c9c4ba'],
        'fill-extrusion-height': height,
        'fill-extrusion-base': ['coalesce', ['get', 'render_min_height'], 0],
        'fill-extrusion-opacity': o.opacity,
        'fill-extrusion-vertical-gradient': true,
      },
    },
    placement: 'below-labels',
    visible: o.visible,
  })
  want.hideBasemapExtrusions = o.visible
}

function selectionLayers(selection: SelectionFeature, want: Desired) {
  want.sources.push({ id: SELECTION_SOURCE, spec: { type: 'geojson', data: selection }, data: selection })
  const top = (spec: Record<string, unknown>): DesiredLayer => ({
    spec: { source: SELECTION_SOURCE, ...spec } as LayerSpecification,
    placement: 'top',
    visible: true,
  })
  want.layers.push(
    top({ id: 'gt-selection-fill', type: 'fill', filter: POLYGON, paint: { 'fill-color': OVERPRINT, 'fill-opacity': 0.07 } }),
    top({
      id: 'gt-selection-casing',
      type: 'line',
      filter: LINEAR,
      layout: { 'line-join': 'round' },
      paint: { 'line-color': '#ffffff', 'line-width': 5, 'line-opacity': 0.85 },
    }),
    top({
      id: 'gt-selection-line',
      type: 'line',
      filter: LINEAR,
      layout: { 'line-join': 'round' },
      paint: { 'line-color': OVERPRINT, 'line-width': 2.25, 'line-dasharray': [2.2, 1.4] },
    }),
    top({
      id: 'gt-selection-point',
      type: 'circle',
      filter: POINT,
      paint: {
        'circle-radius': 8,
        'circle-color': 'rgba(200, 32, 122, 0.15)',
        'circle-stroke-color': OVERPRINT,
        'circle-stroke-width': 3,
      },
    }),
  )
}

export function desiredState(state: OverlayRenderState): Desired {
  const want: Desired = { sources: [], layers: [], images: [], terrain: null, sky: SKY, hideBasemapExtrusions: false }
  // Order matters within a placement: later entries draw on top.
  const order = ['hillshade', 'wms', 'buildings', 'geojson'] as const
  for (const kind of order) {
    for (const o of state.overlays.filter((x) => x.kind === kind && !x.disabled)) {
      if (kind === 'hillshade') hillshadeOverlay(o, want)
      else if (kind === 'wms') wmsOverlay(o, want)
      else if (kind === 'buildings') buildingsOverlay(o, want)
      else geojsonOverlay(o, want)
    }
  }
  const terrain = state.overlays.find((o) => o.kind === 'terrain' && o.visible && !o.disabled)
  if (terrain) {
    want.sources.push({ id: TERRAIN_SOURCE, spec: DEM_SOURCE })
    want.terrain = { source: TERRAIN_SOURCE, exaggeration: TERRAIN_EXAGGERATION }
  }
  if (state.selection) selectionLayers(state.selection, want)
  return want
}

// --- reconciliation -------------------------------------------------------------------------------

const trackedSources = new WeakMap<object, Set<string>>()
const appliedData = new WeakMap<object, Map<string, unknown>>()

function tracking(map: MapLike) {
  if (!trackedSources.has(map)) trackedSources.set(map, new Set())
  if (!appliedData.has(map)) appliedData.set(map, new Map())
  return { sources: trackedSources.get(map)!, data: appliedData.get(map)! }
}

const isOurs = (id: string) => id.startsWith(PREFIX)

function anchorFor(map: MapLike, placement: Placement): string | undefined {
  if (placement === 'top') return undefined
  const order = map.getLayersOrder()
  const typeOf = (id: string) => map.getLayer(id)?.type ?? ''
  if (placement === 'below-labels') {
    const label = order.find((id) => !isOurs(id) && typeOf(id) === 'symbol')
    // Styles without labels (aerial): stay below the selection.
    return label ?? order.find((id) => id.startsWith(SELECTION_SOURCE))
  }
  const line = order.find((id) => !isOurs(id) && ['line', 'symbol', 'fill-extrusion'].includes(typeOf(id)))
  return line ?? order.find(isOurs)
}

export function reconcileOverlays(map: MapLike, state: OverlayRenderState): void {
  const want = desiredState(state)
  const { sources: tracked, data: applied } = tracking(map)

  // Terrain off before its source can be removed.
  if (!want.terrain && map.getTerrain()) map.setTerrain(null)

  const wantedLayers = new Set(want.layers.map((l) => l.spec.id))
  for (const id of map.getLayersOrder()) {
    if (isOurs(id) && !wantedLayers.has(id)) map.removeLayer(id)
  }
  const wantedSources = new Set(want.sources.map((s) => s.id))
  for (const id of [...tracked]) {
    if (wantedSources.has(id)) continue
    if (map.getSource(id)) map.removeSource(id)
    tracked.delete(id)
    applied.delete(id)
  }

  for (const { id, image } of want.images) {
    if (!map.hasImage(id)) map.addImage(id, image)
  }

  for (const source of want.sources) {
    if (!map.getSource(source.id)) {
      map.addSource(source.id, source.spec)
      tracked.add(source.id)
      applied.set(source.id, source.data)
    } else if (source.data !== undefined && applied.get(source.id) !== source.data) {
      void (map.getSource(source.id) as GeoJSONSource).setData(source.data as GeoJSON)
      applied.set(source.id, source.data)
    }
  }

  for (const { spec, placement, visible } of want.layers) {
    const visibility = visible ? 'visible' : 'none'
    if (!map.getLayer(spec.id)) {
      const layout = { ...('layout' in spec ? spec.layout : {}), visibility }
      map.addLayer({ ...spec, layout } as LayerSpecification, anchorFor(map, placement))
      continue
    }
    map.setLayoutProperty(spec.id, 'visibility', visibility)
    for (const [name, value] of Object.entries(('paint' in spec && spec.paint) || {})) {
      map.setPaintProperty(spec.id, name as keyof AllPaintProperties, value)
    }
    if ('filter' in spec && spec.filter) map.setFilter(spec.id, spec.filter)
  }

  // The selection is always drawn last, above labels and anything added later.
  for (const { spec, placement } of want.layers) {
    if (placement === 'top') map.moveLayer(spec.id)
  }

  // Our extrusions replace the basemap's own (OSM Liberty ships one) so heights never render twice.
  for (const id of map.getLayersOrder()) {
    if (!isOurs(id) && map.getLayer(id)?.type === 'fill-extrusion') {
      map.setLayoutProperty(id, 'visibility', want.hideBasemapExtrusions ? 'none' : 'visible')
    }
  }

  if (want.terrain && map.getTerrain()?.source !== want.terrain.source) map.setTerrain(want.terrain)
  // Tilted views show the horizon; without a sky it would be empty page background. A style switch drops it.
  if (map.getSky()?.['sky-color'] !== want.sky['sky-color']) map.setSky(want.sky)
}
