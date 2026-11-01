import { afterEach, describe, expect, test, vi } from 'vitest'
import { safeStorage } from './storage'

describe('safeStorage', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    window.localStorage.clear()
  })

  test('reads back what it wrote', () => {
    safeStorage.set('k', 'v')
    expect(safeStorage.get('k')).toBe('v')
  })

  test('returns null and does not throw when localStorage is unavailable', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new DOMException('denied', 'SecurityError')
    })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('full', 'QuotaExceededError')
    })

    expect(() => safeStorage.set('k', 'v')).not.toThrow()
    expect(safeStorage.get('k')).toBeNull()
  })
})
