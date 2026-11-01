import { type Page, expect } from '@playwright/test'

declare global {
  interface Window {
    __geoMap?: import('maplibre-gl').Map
  }
}

/** Console errors and uncaught exceptions of a page (tests fail on any). */
export function watchConsole(page: Page): string[] {
  const errors: string[] = []
  page.on('console', (message) => {
    if (message.type() === 'error') errors.push(message.text())
  })
  page.on('pageerror', (error) => errors.push(`pageerror: ${error.message}`))
  return errors
}

/** Waits until a real basemap (not the startup placeholder) is loaded and the map is idle. */
export async function waitForMap(page: Page, timeout = 45_000): Promise<void> {
  await page.waitForFunction(
    () => window.__geoMap?.getLayersOrder().some((id) => !id.startsWith('gt-') && id !== 'blank') ?? false,
    null,
    { timeout },
  )
  await waitForIdle(page, timeout)
}

export async function waitForIdle(page: Page, timeout = 45_000): Promise<void> {
  await page.evaluate(
    (ms) =>
      new Promise<void>((resolve) => {
        const map = window.__geoMap!
        const finish = () => setTimeout(resolve, 400)
        const timer = setTimeout(resolve, ms)
        if (map.loaded() && map.areTilesLoaded() && !map.isMoving()) {
          clearTimeout(timer)
          finish()
        } else
          map.once('idle', () => {
            clearTimeout(timer)
            finish()
          })
      }),
    timeout,
  )
}

export async function drawRectangle(page: Page, from: [number, number], to: [number, number]): Promise<void> {
  await page.getByTestId('draw-rectangle').click()
  await page.mouse.move(...from)
  await page.mouse.down()
  await page.mouse.move((from[0] + to[0]) / 2, (from[1] + to[1]) / 2, { steps: 6 })
  await page.mouse.move(...to, { steps: 6 })
  await page.mouse.up()
  await expect(page.getByTestId('selection-chip')).toBeVisible()
}

/** Sends a question and waits for the answer to finish streaming. */
export async function ask(page: Page, question: string): Promise<void> {
  const before = await page.getByTestId('assistant-message').count()
  await page.getByRole('textbox', { name: /Ask about this area|Fragen Sie etwas/ }).fill(question)
  await page.keyboard.press('Enter')
  const answer = page.getByTestId('assistant-message').nth(before)
  await expect(answer).toHaveAttribute('aria-busy', 'false', { timeout: 30_000 })
}

export async function resultLayerIds(page: Page): Promise<string[]> {
  return page.evaluate(() => window.__geoMap!.getLayersOrder().filter((id) => /^gt-geojson-result-.*-circle$|^gt-geojson-result-.*-fill$/.test(id)))
}

/** Photon answers for the two searches the tests use (automated tests do not hit the public API). */
export async function mockPhoton(page: Page): Promise<void> {
  await page.route('https://photon.komoot.io/api/**', async (route) => {
    const q = new URL(route.request().url()).searchParams.get('q') ?? ''
    const cologne = /k(ö|oe)ln|cologne/i.test(q)
    await route.fulfill({
      contentType: 'application/json',
      headers: { 'access-control-allow-origin': '*' },
      body: JSON.stringify({
        features: [
          cologne
            ? { type: 'Feature', geometry: { type: 'Point', coordinates: [6.95814, 50.94133] }, properties: { name: 'Kölner Dom', countrycode: 'DE', osm_key: 'amenity', osm_value: 'place_of_worship', city: 'Köln', state: 'Nordrhein-Westfalen', osm_type: 'W', osm_id: 4532022, extent: [6.9573, 50.9418, 6.9590, 50.9408] } }
            : { type: 'Feature', geometry: { type: 'Point', coordinates: [8.659876, 49.8743133] }, properties: { name: 'Fraunhofer IGD', countrycode: 'DE', osm_key: 'building', osm_value: 'office', street: 'Fraunhoferstraße', housenumber: '5', city: 'Darmstadt', state: 'Hessen', osm_type: 'W', osm_id: 22598446 } },
        ],
      }),
    })
  })
}

export interface LayoutReport {
  overlaps: string[]
  outOfView: string[]
  clippedText: string[]
}

/** Floating controls must not overlap each other or leave the viewport, and labels must not be cut off. */
export async function layoutReport(page: Page): Promise<LayoutReport> {
  return page.evaluate(() => {
    const selectors = [
      '[data-testid=search-box]',
      '[data-testid=draw-toolbar]',
      '[data-testid=layers-button]',
      '[role=radiogroup][aria-label]',
      '[data-testid=layer-panel]',
      '[data-testid=basemap-switcher]',
      '[data-testid=view-mode-toggle]',
      '.maplibregl-ctrl-attrib',
      '.maplibregl-ctrl-scale',
      '[data-testid=aerial-hint]',
      '[data-testid=basemap-notice]',
      '[data-testid=chat-fab]',
    ]
    const sheet = document.querySelector('[data-testid=bottom-sheet]')
    const boxes: { name: string; r: DOMRect }[] = []
    for (const selector of selectors) {
      document.querySelectorAll(selector).forEach((el) => {
        const r = el.getBoundingClientRect()
        if (r.width > 0 && r.height > 0) boxes.push({ name: selector, r })
      })
    }
    if (sheet) boxes.push({ name: 'bottom-sheet', r: sheet.getBoundingClientRect() })
    const overlaps: string[] = []
    for (let i = 0; i < boxes.length; i++) {
      for (let j = i + 1; j < boxes.length; j++) {
        const a = boxes[i].r
        const b = boxes[j].r
        const x = Math.min(a.right, b.right) - Math.max(a.left, b.left)
        const y = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top)
        if (x > 2 && y > 2) overlaps.push(`${boxes[i].name} x ${boxes[j].name}`)
      }
    }
    const outOfView = boxes
      .filter(({ r }) => r.left < -1 || r.top < -1 || r.right > innerWidth + 1 || r.bottom > innerHeight + 1)
      .map((b) => b.name)
    const clippedText = [...document.querySelectorAll('button, h2, h3, label, [role=option]')]
      .filter((el) => (el.textContent ?? '').trim().length > 0)
      .filter((el) => el.scrollWidth > el.clientWidth + 1 && !el.closest('.truncate') && !el.classList.contains('truncate'))
      .map((el) => (el.textContent ?? '').trim().slice(0, 40))
    return { overlaps, outOfView, clippedText }
  })
}
