import { expect, test } from 'vitest'
import { formatArea } from './format'

test.each([
  [8420, 'en', '8,420 m²'],
  [8420, 'de', '8.420 m²'],
  [99_000, 'en', '99,000 m²'],
  [420_000, 'de', '0,42 km²'],
  [420_000, 'en', '0.42 km²'],
  [35_500_000, 'en', '35.5 km²'],
  [357_000_000_000, 'de', '357.000 km²'],
  [0, 'en', '0 m²'],
] as const)('formatArea(%d, %s) is %s', (m2, lang, expected) => {
  expect(formatArea(m2, lang)).toBe(expected)
})
