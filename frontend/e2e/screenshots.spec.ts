import { type Page, expect, test } from '@playwright/test'
import { writeFileSync } from 'node:fs'
import { ask, drawRectangle, layoutReport, waitForIdle, waitForMap, watchConsole } from './helpers'

/**
 * Screenshots into frontend/screenshots: five states at 1440x900 and 390x844, in English and German.
 * Run with `npx playwright test --project=screenshots`.
 */
const OUT = 'screenshots'

const VIEWPORTS = {
  desktop: { size: { width: 1440, height: 900 }, rect: [[360, 300], [700, 600]] as [number, number][] },
  mobile: { size: { width: 390, height: 844 }, rect: [[80, 300], [300, 520]] as [number, number][] },
}
const QUESTIONS = {
  en: 'Where could new EV chargers go in this area?',
  de: 'Wo könnten in diesem Gebiet neue Ladesäulen hin?',
}

const reports: Record<string, unknown> = {}

async function shot(page: Page, name: string) {
  await waitForIdle(page)
  await page.screenshot({ path: `${OUT}/${name}.png` })
  const report = await layoutReport(page)
  reports[name] = report
  expect(report, `layout of ${name}`).toEqual({ overlaps: [], outOfView: [], clippedText: [] })
}

test.afterAll(() => {
  writeFileSync(`${OUT}/layout-report.json`, `${JSON.stringify(reports, null, 2)}\n`)
})

for (const [viewport, config] of Object.entries(VIEWPORTS)) {
  for (const lang of ['en', 'de'] as const) {
    test(`${viewport} ${lang}`, async ({ page }) => {
      const errors = watchConsole(page)
      await page.setViewportSize(config.size)
      await page.addInitScript((language) => {
        if (!sessionStorage.getItem('screenshots-init')) {
          localStorage.clear()
          localStorage.setItem('geo-toolbox.lang', language)
          sessionStorage.setItem('screenshots-init', '1')
        }
      }, lang)
      const prefix = `${viewport}-${lang}`
      const mobile = viewport === 'mobile'

      await page.goto('/')
      await waitForMap(page)
      await shot(page, `${prefix}-1-empty`)

      await drawRectangle(page, config.rect[0], config.rect[1])
      await shot(page, `${prefix}-2-selection`)

      await ask(page, QUESTIONS[lang])
      await page.waitForFunction(() => !window.__geoMap!.isMoving())
      await shot(page, `${prefix}-3-conversation`)

      if (mobile) {
        // Back to the peek state, so the layer panel and the 3D view get the screen.
        const handle = page.getByRole('button', { name: /Drag to resize the chat|Ziehen, um die Chatgröße zu ändern/ })
        await handle.click()
        await handle.click()
        await expect(page.getByTestId('bottom-sheet')).toHaveAttribute('data-snap', 'peek')
      }
      await page.getByTestId('layers-button').click()
      await expect(page.getByTestId('layer-panel')).toBeVisible()
      await shot(page, `${prefix}-4-layers`)

      await page.getByTestId('layers-button').click()
      await page.getByTestId('view-mode-toggle').click()
      await page.waitForFunction(() => window.__geoMap!.getPitch() > 55 && !window.__geoMap!.isMoving())
      await shot(page, `${prefix}-5-3d`)

      expect(errors, 'console errors').toEqual([])
    })
  }
}
