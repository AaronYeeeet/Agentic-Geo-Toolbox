import { expect, test } from 'vitest'
import { popupContent } from './popup'

test('popup lists properties as text, so markup in data is never interpreted', () => {
  const node = popupContent('Schools (Demo data)', { name: 'Demo school 1', note: '<img src=x onerror=alert(1)>', pupils: 523 })

  expect(node.querySelector('h3')?.textContent).toBe('Demo school 1')
  expect(node.textContent).toContain('Schools (Demo data)')
  expect(node.textContent).toContain('<img src=x onerror=alert(1)>')
  expect(node.querySelector('img')).toBeNull()
  expect([...node.querySelectorAll('th')].map((th) => th.textContent)).toEqual(['name', 'note', 'pupils'])
})

test('popup says when a feature has no properties', () => {
  expect(popupContent('Upload', {}).textContent).toContain('This feature has no properties.')
})

test('popup title uses a name-like column in any case (German CSVs often use "Name" or "Bezeichnung")', () => {
  expect(popupContent('ladepunkte.csv', { Name: 'IGD', kW: '22' }).querySelector('h3')?.textContent).toBe('IGD')
  expect(popupContent('schulen.csv', { Bezeichnung: 'Lichtenbergschule' }).querySelector('h3')?.textContent).toBe('Lichtenbergschule')
})
