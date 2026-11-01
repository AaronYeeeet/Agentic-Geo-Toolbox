/**
 * GetMap tile template for a WMS layer in EPSG:3857. MapLibre replaces `{bbox-epsg-3857}` per tile, so the token
 * must stay unescaped while every other value is URL-encoded.
 */
export function wmsTileUrl(
  baseUrl: string,
  layers: string[],
  { format = 'image/png', size = 256, transparent }: { format?: string; size?: number; transparent?: boolean } = {},
): string {
  const params = new URLSearchParams({
    SERVICE: 'WMS',
    VERSION: '1.3.0',
    REQUEST: 'GetMap',
    LAYERS: layers.join(','),
    STYLES: '',
    CRS: 'EPSG:3857',
  })
  const tail = new URLSearchParams({
    WIDTH: String(size),
    HEIGHT: String(size),
    FORMAT: format,
    TRANSPARENT: (transparent ?? format === 'image/png') ? 'TRUE' : 'FALSE',
  })
  const separator = baseUrl.includes('?') ? '&' : '?'
  return `${baseUrl}${separator}${params.toString()}&BBOX={bbox-epsg-3857}&${tail.toString()}`
}
