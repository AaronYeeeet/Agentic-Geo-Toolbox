import { expect, test } from 'vitest'
import { area as turfArea, bboxPolygon } from '@turf/turf'
import { selectionFromBounds, selectionFromDrawing, selectionFromFeature } from './selection'

test('a picked building becomes a feature selection with its area and name', () => {
  const selection = selectionFromFeature({
    type: 'Feature',
    geometry: {
      type: 'Polygon',
      coordinates: [[[8.6594, 49.874], [8.6604, 49.874], [8.6604, 49.8745], [8.6594, 49.8745], [8.6594, 49.874]]],
    },
    properties: { name: 'Fraunhofer IGD' },
  })

  expect(selection?.properties.kind).toBe('feature')
  expect(selection?.properties.label).toBe('Fraunhofer IGD')
  expect(selection?.properties.area_m2).toBeGreaterThan(3000)
})

test('a picked point keeps its point geometry and has no area', () => {
  const selection = selectionFromFeature({
    type: 'Feature',
    geometry: { type: 'Point', coordinates: [8.65, 49.87] },
    properties: { name: 'Demo school 1' },
  })

  expect(selection?.geometry.type).toBe('Point')
  expect(selection?.properties.area_m2).toBe(0)
})

test('lines and empty geometries are not selectable', () => {
  expect(
    selectionFromFeature({ type: 'Feature', geometry: { type: 'LineString', coordinates: [[8, 49], [9, 50]] }, properties: {} }),
  ).toBeNull()
})

test('the current view becomes a view selection', () => {
  const selection = selectionFromBounds([8.64, 49.86, 8.66, 49.88])

  expect(selection.properties.kind).toBe('view')
  expect(selection.geometry.type).toBe('Polygon')
  expect(selection.properties.area_m2).toBeGreaterThan(3_000_000)
})

test('a self-intersecting (bowtie) polygon counts both lobes instead of letting them cancel out', () => {
  const bowtie = {
    type: 'Feature' as const,
    geometry: { type: 'Polygon' as const, coordinates: [[[8.64, 49.86], [8.66, 49.88], [8.66, 49.86], [8.64, 49.88], [8.64, 49.86]]] },
    properties: {},
  }

  const selection = selectionFromDrawing(bowtie, 'polygon')

  const half = turfArea(bboxPolygon([8.64, 49.86, 8.66, 49.88])) / 2
  expect(selection?.properties.area_m2).toBeGreaterThan(half * 0.97)
  expect(selection?.properties.area_m2).toBeLessThan(half * 1.03)
})
