import type { StyleSpecification } from '@maplibre/maplibre-gl-style-spec'
import { afterEach, describe, expect, test, vi } from 'vitest'
import { loadBasemapStyle, patchStyle, resetStyleCache } from './styles'

const tiny = (name: string): StyleSpecification => ({
  version: 8,
  name,
  sources: {},
  layers: [{ id: 'bg', type: 'background' }],
})

function mockFetch(handler: (url: string) => Promise<Response>) {
  return vi.spyOn(globalThis, 'fetch').mockImplementation((input) => handler(String(input)))
}

const json = (body: unknown) => Promise.resolve(new Response(JSON.stringify(body), { status: 200 }))

describe('loadBasemapStyle', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    resetStyleCache()
  })

  test('loads the basemap.de style when BKG answers', async () => {
    mockFetch((url) => json(tiny(url.includes('bm_web_col') ? 'bkg' : 'other')))

    const result = await loadBasemapStyle('official', [])

    expect(result.fallback).toBe(false)
    expect(result.style.name).toBe('bkg')
  })

  test('falls back to OpenFreeMap when BKG does not answer, and remembers it', async () => {
    const fetch = mockFetch((url) =>
      url.includes('geodatenzentrum') ? Promise.reject(new TypeError('Failed to fetch')) : json(tiny('openfreemap')),
    )

    const first = await loadBasemapStyle('light', [])
    const second = await loadBasemapStyle('light', [])

    expect(first).toMatchObject({ fallback: true, style: { name: 'openfreemap' } })
    expect(second.fallback).toBe(true)
    const bkgCalls = fetch.mock.calls.filter(([url]) => String(url).includes('geodatenzentrum'))
    expect(bkgCalls).toHaveLength(1)
  })

  test('builds the aerial style locally without fetching', async () => {
    const fetch = mockFetch(() => json({}))

    const result = await loadBasemapStyle('aerial', [])

    expect(fetch).not.toHaveBeenCalled()
    expect(result.style.layers[0].id).toBe('aerial-background')
  })
})

test('patchStyle guards numeric comparisons on a missing ref_length (OpenFreeMap shields)', () => {
  const style: StyleSpecification = {
    version: 8,
    sources: {},
    layers: [
      {
        id: 'highway-shield-non-us',
        type: 'symbol',
        source: 'openmaptiles',
        filter: ['all', ['<=', ['get', 'ref_length'], 6], ['==', ['get', 'class'], 'motorway']],
      },
    ],
  }

  const patched = patchStyle(style)

  expect(JSON.stringify(patched.layers[0])).toContain('["coalesce",["get","ref_length"],99]')
  expect(JSON.stringify(patched.layers[0])).toContain('["==",["get","class"],"motorway"]')
})
