import { expect, test } from 'vitest'
import { wmsTileUrl } from './wms'

test('builds a WMS 1.3.0 GetMap template in EPSG:3857 with an unescaped bbox token', () => {
  const url = wmsTileUrl('https://example.org/wms', ['he_dop20_rgb'], { format: 'image/jpeg' })

  expect(url).toBe(
    'https://example.org/wms?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetMap&LAYERS=he_dop20_rgb&STYLES=' +
      '&CRS=EPSG%3A3857&BBOX={bbox-epsg-3857}&WIDTH=256&HEIGHT=256&FORMAT=image%2Fjpeg&TRANSPARENT=FALSE',
  )
})

test('keeps existing query parameters and joins several layers', () => {
  const url = wmsTileUrl('https://example.org/wms?map=dop', ['a', 'b'], { transparent: true, size: 512 })

  expect(url.startsWith('https://example.org/wms?map=dop&SERVICE=WMS')).toBe(true)
  expect(url).toContain('LAYERS=a%2Cb')
  expect(url).toContain('WIDTH=512&HEIGHT=512')
  expect(url).toContain('FORMAT=image%2Fpng&TRANSPARENT=TRUE')
})
