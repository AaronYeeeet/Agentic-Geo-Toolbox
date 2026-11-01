import type { StateStorage } from 'zustand/middleware'

/**
 * localStorage that never throws: private windows, blocked site data and full quotas make the browser throw on
 * access, and none of what we store is essential (it only restores UI preferences).
 */
export const safeStorage = {
  get(key: string): string | null {
    try {
      return window.localStorage.getItem(key)
    } catch {
      return null
    }
  },
  set(key: string, value: string): void {
    try {
      window.localStorage.setItem(key, value)
    } catch {
      // Preference is lost for this session; the app keeps working.
    }
  },
  remove(key: string): void {
    try {
      window.localStorage.removeItem(key)
    } catch {
      // ignore
    }
  },
}

/** Adapter for zustand's persist middleware. */
export const zustandStorage: StateStorage = {
  getItem: (name) => safeStorage.get(name),
  setItem: (name, value) => safeStorage.set(name, value),
  removeItem: (name) => safeStorage.remove(name),
}
