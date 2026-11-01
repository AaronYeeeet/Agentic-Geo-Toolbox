import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'
import { ask, drawRectangle, waitForMap } from './helpers'

/**
 * Accessibility audit (WCAG 2.1 A/AA rules of axe) of the main states. The map canvas itself is excluded: it is a
 * WebGL image, and its text alternative is the chat and the layer panel.
 */
async function audit(page: import('@playwright/test').Page, label: string) {
  const results = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
    .exclude('.maplibregl-canvas')
    .analyze()
  const summary = results.violations.map((v) => `${v.id} (${v.impact}): ${v.nodes.slice(0, 3).map((n) => n.target.join(' ')).join(' | ')}`)
  expect(summary, `axe violations in ${label}`).toEqual([])
}

test('desktop: empty, conversation and layer panel pass axe', async ({ page }) => {
  await page.goto('/')
  await waitForMap(page)
  await audit(page, 'empty')
  await drawRectangle(page, [360, 300], [700, 600])
  await ask(page, 'Where could new EV chargers go in this area?')
  await audit(page, 'conversation')
  await page.getByTestId('layers-button').click()
  await audit(page, 'layer panel')
})

test.describe('phone', () => {
  test.use({ viewport: { width: 390, height: 844 } })
  test('peek and half sheet pass axe', async ({ page }) => {
    await page.goto('/')
    await waitForMap(page)
    await audit(page, 'peek')
    await ask(page, 'Show all schools in the selected area.')
    await audit(page, 'half')
  })
})
