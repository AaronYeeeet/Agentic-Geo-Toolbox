/* In-memory stand-in for the parts of maplibre-gl's Map that the overlay code uses (tests only). */
import type { LayerSpecification, SourceSpecification, TerrainSpecification } from '@maplibre/maplibre-gl-style-spec'

interface FakeSource {
  spec: SourceSpecification
  data?: unknown
  setData(data: unknown): void
}

export class FakeMap {
  layers: LayerSpecification[] = []
  sources: Record<string, FakeSource> = {}
  terrain: TerrainSpecification | null = null
  sky: Record<string, unknown> | undefined = undefined
  images = new Set<string>()
  setDataCalls = 0

  constructor(basemapLayers: LayerSpecification[] = []) {
    this.layers = [...basemapLayers]
  }

  /** Simulates map.setStyle(): everything we added is gone. */
  reloadStyle(basemapLayers: LayerSpecification[] = []) {
    this.layers = [...basemapLayers]
    this.sources = {}
    this.terrain = null
    this.sky = undefined
    this.images.clear()
  }

  getStyle() {
    return { version: 8 as const, sources: {}, layers: this.layers }
  }
  getLayersOrder() {
    return this.layers.map((l) => l.id)
  }
  getLayer(id: string) {
    return this.layers.find((l) => l.id === id)
  }
  addLayer(layer: LayerSpecification, beforeId?: string) {
    if (this.getLayer(layer.id)) throw new Error(`layer ${layer.id} exists`)
    if ('source' in layer && typeof layer.source === 'string' && !this.sources[layer.source]) {
      throw new Error(`source ${layer.source} missing for ${layer.id}`)
    }
    const index = beforeId ? this.layers.findIndex((l) => l.id === beforeId) : -1
    if (index === -1) this.layers.push(structuredClone(layer))
    else this.layers.splice(index, 0, structuredClone(layer))
    return this
  }
  moveLayer(id: string, beforeId?: string) {
    const layer = this.getLayer(id)
    if (!layer) throw new Error(`layer ${id} missing`)
    this.layers = this.layers.filter((l) => l.id !== id)
    const index = beforeId ? this.layers.findIndex((l) => l.id === beforeId) : -1
    if (index === -1) this.layers.push(layer)
    else this.layers.splice(index, 0, layer)
    return this
  }
  removeLayer(id: string) {
    this.layers = this.layers.filter((l) => l.id !== id)
    return this
  }
  getSource(id: string) {
    return this.sources[id]
  }
  addSource(id: string, spec: SourceSpecification) {
    if (this.sources[id]) throw new Error(`source ${id} exists`)
    const source: FakeSource = {
      spec,
      data: 'data' in spec ? spec.data : undefined,
      setData: (data: unknown) => {
        source.data = data
        this.setDataCalls += 1
      },
    }
    this.sources[id] = source
    return this
  }
  removeSource(id: string) {
    if (this.layers.some((l) => 'source' in l && l.source === id)) throw new Error(`source ${id} in use`)
    delete this.sources[id]
    return this
  }
  setLayoutProperty(id: string, name: string, value: unknown) {
    const layer = this.getLayer(id) as { layout?: Record<string, unknown> } | undefined
    if (!layer) throw new Error(`layer ${id} missing`)
    layer.layout = { ...layer.layout, [name]: value }
    return this
  }
  setPaintProperty(id: string, name: string, value: unknown) {
    const layer = this.getLayer(id) as { paint?: Record<string, unknown> } | undefined
    if (!layer) throw new Error(`layer ${id} missing`)
    layer.paint = { ...layer.paint, [name]: value }
    return this
  }
  setFilter(id: string, filter: unknown) {
    const layer = this.getLayer(id) as { filter?: unknown } | undefined
    if (!layer) throw new Error(`layer ${id} missing`)
    layer.filter = filter
    return this
  }
  setTerrain(terrain: TerrainSpecification | null) {
    this.terrain = terrain
    return this
  }
  getTerrain() {
    return this.terrain
  }
  setSky(sky?: Record<string, unknown>) {
    this.sky = sky
  }
  getSky() {
    return this.sky
  }
  hasImage(id: string) {
    return this.images.has(id)
  }
  addImage(id: string) {
    this.images.add(id)
    return this
  }

  ids() {
    return this.layers.map((l) => l.id)
  }
}
