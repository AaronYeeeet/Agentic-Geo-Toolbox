import type { Feature } from 'geojson'
import type { Map as MapLibreMap, MapMouseEvent } from 'maplibre-gl'
import {
  TerraDraw,
  TerraDrawPolygonMode,
  TerraDrawRectangleMode,
  ValidateMinAreaSquareMeters,
  ValidateNotSelfIntersecting,
} from 'terra-draw'
import { TerraDrawMapLibreGLAdapter } from 'terra-draw-maplibre-gl-adapter'
import { selectionFromDrawing, selectionFromFeature } from '@/features/draw/selection'
import { useDrawStore } from '@/store/drawStore'
import { useMapStore } from '@/store/mapStore'
import { useSelectionStore } from '@/store/selectionStore'
import { OVERPRINT } from './config'
import { PREFIX } from './overlays'

const DRAW_STYLE = {
  fillColor: OVERPRINT,
  fillOpacity: 0.08,
  outlineColor: OVERPRINT,
  outlineWidth: 2,
} as const

const POINT_STYLE = {
  closingPointColor: OVERPRINT,
  closingPointOutlineColor: '#ffffff',
  closingPointWidth: 5,
  closingPointOutlineWidth: 2,
} as const

/** Layers whose features can be picked as the selection: agent results, uploads, buildings and places. */
function pickableLayers(map: MapLibreMap): string[] {
  return map.getLayersOrder().filter((id) => {
    const type = map.getLayer(id)?.type
    if (id.startsWith(PREFIX)) {
      return (id.startsWith('gt-geojson-') && !id.includes('-highlight-')) || id === 'gt-buildings'
    }
    return /building|poi/i.test(id) && ['fill', 'fill-extrusion', 'symbol', 'circle'].includes(type ?? '')
  })
}

/**
 * Selection tools on the map. Terra Draw runs only while the rectangle or polygon tool is active, so it never
 * captures normal map interaction; the finished shape moves into the selection store and Terra Draw stops.
 */
export function attachDraw(map: MapLibreMap): () => void {
  let draw: TerraDraw | null = null
  let pick: ((event: MapMouseEvent) => void) | null = null

  const finishWith = (selection: ReturnType<typeof selectionFromFeature>) => {
    if (selection) useSelectionStore.getState().setSelection(selection)
    useDrawStore.getState().setTool(null)
  }

  const stop = () => {
    if (draw) {
      try {
        draw.stop()
      } catch {
        // The style may already be gone (basemap switch); nothing left to clean up.
      }
      draw = null
    }
    if (pick) {
      map.off('click', pick)
      pick = null
    }
    map.getCanvas().style.cursor = ''
  }

  const startDrawing = (tool: 'rectangle' | 'polygon') => {
    stop()
    const instance = new TerraDraw({
      adapter: new TerraDrawMapLibreGLAdapter({ map }),
      modes: [
        new TerraDrawRectangleMode({
          drawInteraction: 'click-move-or-drag',
          styles: DRAW_STYLE,
          // A stray click would otherwise finish a rectangle of a few square centimetres.
          validation: (feature, { updateType }) =>
            updateType === 'finish' ? ValidateMinAreaSquareMeters(feature, 10) : { valid: true },
        }),
        new TerraDrawPolygonMode({
          styles: { ...DRAW_STYLE, ...POINT_STYLE },
          // Bowties have no meaningful area; refuse the point that would make the outline cross itself.
          validation: (feature, { updateType }) =>
            updateType === 'provisional' ? { valid: true } : ValidateNotSelfIntersecting(feature),
        }),
      ],
    })
    instance.start()
    instance.setMode(tool)
    instance.on('finish', (id) => {
      const feature = instance.getSnapshotFeature(id)
      finishWith(feature ? selectionFromDrawing(feature as Feature, tool) : null)
    })
    draw = instance
  }

  const startPicking = () => {
    stop()
    map.getCanvas().style.cursor = 'crosshair'
    pick = (event) => {
      const [hit] = map.queryRenderedFeatures(event.point, { layers: pickableLayers(map) })
      if (!hit) return
      finishWith(selectionFromFeature({ type: 'Feature', geometry: hit.geometry, properties: hit.properties }))
    }
    map.on('click', pick)
  }

  const apply = (tool: ReturnType<typeof useDrawStore.getState>['tool']) => {
    if (tool === 'rectangle' || tool === 'polygon') startDrawing(tool)
    else if (tool === 'feature') startPicking()
    else stop()
  }

  const onKey = (event: KeyboardEvent) => {
    if (event.key === 'Escape' && useDrawStore.getState().tool) useDrawStore.getState().setTool(null)
  }
  window.addEventListener('keydown', onKey)

  const unsubscribers = [
    useDrawStore.subscribe((state, previous) => {
      if (state.tool !== previous.tool) apply(state.tool)
    }),
    // A style switch removes Terra Draw's layers; end the drawing instead of leaving it half alive.
    useMapStore.subscribe((state, previous) => {
      if (state.basemap !== previous.basemap) useDrawStore.getState().setTool(null)
    }),
  ]

  return () => {
    stop()
    window.removeEventListener('keydown', onKey)
    unsubscribers.forEach((unsubscribe) => unsubscribe())
  }
}
