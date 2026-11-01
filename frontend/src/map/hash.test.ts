import { describe, expect, test } from 'vitest'
import { readHashParams, withHashParams } from './hash'

describe('URL hash parameters', () => {
  test('reads basemap and view mode next to the map position', () => {
    expect(readHashParams('#map=16/49.87/8.65/0/0&basemap=relief&mode=3d')).toEqual({ basemap: 'relief', mode: '3d' })
  })

  test('ignores unknown values', () => {
    expect(readHashParams('#basemap=moon&mode=4d')).toEqual({})
  })

  test('writes parameters and keeps the map position untouched', () => {
    expect(withHashParams('#map=16/49.87/8.65', { basemap: 'aerial', mode: '3d' })).toBe(
      '#map=16/49.87/8.65&basemap=aerial&mode=3d',
    )
  })

  test('omits defaults so plain views keep short URLs', () => {
    expect(withHashParams('#map=16/1/2&basemap=relief&mode=3d', { basemap: 'osm', mode: '2d' })).toBe('#map=16/1/2')
  })
})
