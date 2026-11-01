/**
 * Agent protocol. Mirrors backend/app/protocol/models.py; change both together.
 */
import type { Feature, FeatureCollection, MultiPolygon, Point, Polygon } from 'geojson'

export type Language = 'en' | 'de'
export type BBoxTuple = [number, number, number, number]

export interface ChatMessageIn {
  role: 'user' | 'assistant'
  content: string
}

export interface Viewport {
  bbox: BBoxTuple
  center: [number, number]
  zoom: number
  pitch: number
  bearing: number
}

export interface UploadMeta {
  id: string
  name: string
  feature_count: number
  bbox: number[]
  geometry_types: string[]
  sample_properties: Record<string, unknown>
}

export interface ChatContext {
  ui_language: Language
  viewport?: Viewport
  selection?: Feature<Polygon | MultiPolygon | Point, Record<string, unknown>>
  active_layers: string[]
  uploads: UploadMeta[]
}

export interface ChatRequest {
  conversation_id: string
  messages: ChatMessageIn[]
  context: ChatContext
}

export type MapAction =
  | { type: 'fly_to'; center: [number, number]; zoom: number }
  | { type: 'fit_bounds'; bbox: BBoxTuple }
  | { type: 'add_geojson_layer'; id: string; title: string; geojson: FeatureCollection; color: string; kind: 'result' | 'demo' }
  | { type: 'remove_layer'; id: string }
  | { type: 'set_layer_visibility'; id: string; visible: boolean }
  | { type: 'highlight_features'; layer_id: string; feature_ids: string[] }
  | { type: 'add_wms_layer'; id: string; title: string; url: string; layers: string[]; attribution: string }
  | { type: 'set_basemap'; id: 'osm' | 'official' | 'light' | 'relief' | 'aerial' }
  | { type: 'set_view_mode'; mode: '2d' | '3d' }

export interface SourceItem {
  title: string
  url: string
  license: string
}

export type AgentEvent =
  | { event: 'run_start'; data: { run_id: string } }
  | { event: 'text_delta'; data: { text: string } }
  | { event: 'tool_start'; data: { id: string; name: string; label: string } }
  | { event: 'tool_end'; data: { id: string; status: 'ok' | 'error'; summary: string; duration_ms: number } }
  | { event: 'map_action'; data: MapAction }
  | { event: 'sources'; data: { items: SourceItem[] } }
  | { event: 'error'; data: { message: string; retryable: boolean } }
  | { event: 'done'; data: Record<string, never> }
