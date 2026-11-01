import type {
  RasterDEMSourceSpecification,
  SkySpecification,
  VectorSourceSpecification,
} from '@maplibre/maplibre-gl-style-spec'

/** Start view: Fraunhofer IGD, Darmstadt (OSM way 22598446), zoom about 16. */
export const START_VIEW = { center: [8.65989, 49.87425] as [number, number], zoom: 16.2 }

/** Overprint colour for the user's area (selection, highlights). Keep in sync with --overprint in index.css. */
export const OVERPRINT = '#c8207a'

/**
 * Terrain: Mapterhorn, terrarium-encoded WebP tiles (Hessen at 1 m from DGM1). `maxzoom` must be set, or MapLibre
 * requests z17+ tiles that return 404.
 */
export const DEM_SOURCE: RasterDEMSourceSpecification = {
  type: 'raster-dem',
  tiles: ['https://tiles.mapterhorn.com/{z}/{x}/{y}.webp'],
  encoding: 'terrarium',
  tileSize: 512,
  maxzoom: 16,
  attribution: '<a href="https://mapterhorn.com/attribution" target="_blank" rel="noopener">© Mapterhorn</a>',
}

export const TERRAIN_EXAGGERATION = 1.3

/** A pale, hazy sky for pitched 3D views: calm, close to the panel colours, never competing with the map. */
export const SKY: SkySpecification = {
  'sky-color': '#cfe0ec',
  'horizon-color': '#eef3f6',
  'fog-color': '#eef3f6',
  'sky-horizon-blend': 0.6,
  'horizon-fog-blend': 0.7,
  'fog-ground-blend': 0.85,
}

/** OpenFreeMap vector tiles (OpenMapTiles schema) for 2.5D building heights over any basemap. Use the TileJSON:
 * its tile URLs change weekly. */
export const OPENFREEMAP_SOURCE: VectorSourceSpecification = {
  type: 'vector',
  url: 'https://tiles.openfreemap.org/planet',
}
