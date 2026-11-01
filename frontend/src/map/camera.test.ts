import { beforeEach, expect, test, vi } from 'vitest'
import { fitToBBox } from './camera'

const fitBounds = vi.fn()
vi.mock('./mapRef', () => ({ getMap: () => ({ fitBounds }) }))

beforeEach(() => fitBounds.mockClear())

test('fitToBBox ignores boxes outside longitude/latitude ranges instead of throwing', () => {
  expect(fitToBBox([475600, 5524600, 475700, 5524700])).toBe(false)
  expect(fitBounds).not.toHaveBeenCalled()
})

test('fitToBBox fits valid boxes with padding for the floating panels', () => {
  expect(fitToBBox([8.6, 49.8, 8.7, 49.9])).toBe(true)
  expect(fitBounds).toHaveBeenCalledWith([8.6, 49.8, 8.7, 49.9], expect.objectContaining({ padding: expect.objectContaining({ top: expect.any(Number), bottom: expect.any(Number) }) }))
})
