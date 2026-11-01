import { beforeEach, expect, test, vi } from 'vitest'
import { BUILT_IN_OVERLAYS, useLayerStore } from '@/store/layerStore'
import { useNoticeStore } from '@/store/noticeStore'
import { addUploads } from './addUploads'

const fitBounds = vi.fn()
vi.mock('@/map/mapRef', () => ({ getMap: () => ({ fitBounds }) }))

beforeEach(() => {
  useLayerStore.setState({ overlays: BUILT_IN_OVERLAYS })
  useNoticeStore.setState({ notices: [] })
  fitBounds.mockClear()
})

test('an upload becomes a "My data" layer, the map zooms to it and a notice confirms it', async () => {
  await addUploads([new File(['name,lat,lon\nA,49.87,8.65\nB,49.88,8.66\n'], 'stations.csv')])

  const upload = useLayerStore.getState().overlays.find((o) => o.group === 'mydata')
  expect(upload).toMatchObject({ kind: 'geojson', title: 'stations.csv', featureCount: 2, removable: true, visible: true })
  expect(upload?.upload).toMatchObject({ format: 'CSV', sampleProperties: { name: 'A' } })
  expect(fitBounds).toHaveBeenCalledWith([8.65, 49.87, 8.66, 49.88], expect.anything())
  expect(useNoticeStore.getState().notices.at(-1)).toMatchObject({ kind: 'info', text: 'Added stations.csv with 2 features' })
})

test('a broken file leaves the layers alone and shows an actionable error', async () => {
  await addUploads([new File(['name,street\nA,Main St\n'], 'addresses.csv')])

  expect(useLayerStore.getState().overlays.some((o) => o.group === 'mydata')).toBe(false)
  expect(useNoticeStore.getState().notices.at(-1)?.kind).toBe('error')
  expect(useNoticeStore.getState().notices.at(-1)?.text).toContain('addresses.csv has no latitude and longitude columns')
})
