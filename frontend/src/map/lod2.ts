import type { Map as MapLibreMap } from 'maplibre-gl'

/**
 * True 3D buildings (experimental): a 3D Tiles tileset drawn by deck.gl's Tile3DLayer through
 * `@deck.gl/maplibre` (MapLibre v6 compatible). deck.gl and loaders.gl are imported only when this runs, so the
 * main bundle stays small.
 *
 * The basemap.de LoD2 tileset (`gdz_basemapde_3d_gebaeude/lod2_4326_null.json`, ECEF content as the 3D Tiles spec
 * requires) could not be reached so far, so the LoD2 toggle stays disabled; the pipeline itself was
 * verified on a public 3D Tiles sample.
 */
export const LOD2_TILESET = 'https://sgx.geodatenzentrum.de/gdz_basemapde_3d_gebaeude/lod2_4326_null.json'

export interface TilesetInfo {
  center: [number, number, number]
  zoom: number
}

export interface Lod2Handle {
  setOpacity: (opacity: number) => void
  remove: () => void
}

export async function attachLod2(
  map: MapLibreMap,
  url: string,
  callbacks: { onLoad?: (info: TilesetInfo) => void; onTile?: () => void; onError?: (message: string) => void } = {},
): Promise<Lod2Handle> {
  const [{ MapLibreOverlay }, { Tile3DLayer }, { Tiles3DLoader }] = await Promise.all([
    import('@deck.gl/maplibre'),
    import('@deck.gl/geo-layers'),
    import('@loaders.gl/3d-tiles'),
  ])

  const layer = (opacity: number) =>
    new Tile3DLayer({
      id: 'gt-lod2',
      data: url,
      loader: Tiles3DLoader,
      opacity,
      onTilesetLoad: (tileset) => {
        const [lng, lat, height] = tileset.cartographicCenter ?? [0, 0, 0]
        callbacks.onLoad?.({ center: [lng, lat, height], zoom: tileset.zoom })
      },
      onTileLoad: () => callbacks.onTile?.(),
      onTileError: (_tile, _url, message) => callbacks.onError?.(String(message)),
    })

  const overlay = new MapLibreOverlay({ interleaved: true, layers: [layer(1)] })
  map.addControl(overlay)
  return {
    setOpacity: (opacity) => overlay.setProps({ layers: [layer(opacity)] }),
    remove: () => map.removeControl(overlay),
  }
}
