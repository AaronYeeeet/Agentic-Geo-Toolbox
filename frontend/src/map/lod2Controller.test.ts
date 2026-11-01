import { expect, test } from 'vitest'
import { BUILT_IN_OVERLAYS, type Overlay } from '@/store/layerStore'
import { shouldShowLod2 } from './lod2Controller'

const withLod2 = (patch: Partial<Overlay>) =>
  BUILT_IN_OVERLAYS.map((o) => (o.id === 'lod2' ? { ...o, ...patch } : o))

test('LoD2 shows only when enabled, switched on and in 3D', () => {
  expect(shouldShowLod2(withLod2({ disabled: false, visible: true }), '3d')).toBe(true)
  expect(shouldShowLod2(withLod2({ disabled: false, visible: true }), '2d')).toBe(false)
  expect(shouldShowLod2(withLod2({ disabled: false, visible: false }), '3d')).toBe(false)
  // It ships disabled: the basemap.de tileset could not be verified.
  expect(shouldShowLod2(withLod2({ visible: true }), '3d')).toBe(false)
})
