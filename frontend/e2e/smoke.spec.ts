import { expect, test } from '@playwright/test'
import { ask, drawRectangle, mockPhoton, resultLayerIds, waitForIdle, waitForMap, watchConsole } from './helpers'

/** End-to-end smoke tests of the main features. */
let errors: string[] = []

test.beforeEach(async ({ page }) => {
  errors = watchConsole(page)
  await mockPhoton(page)
})

test.afterEach(() => {
  expect(errors, 'console errors').toEqual([])
})

test('opens at Fraunhofer IGD in Darmstadt with the OSM basemap and visible attribution', async ({ page }) => {
  await page.goto('/')
  await waitForMap(page)

  const view = await page.evaluate(() => ({ center: window.__geoMap!.getCenter().toArray(), zoom: window.__geoMap!.getZoom() }))
  expect(view.center[0]).toBeCloseTo(8.6599, 2)
  expect(view.center[1]).toBeCloseTo(49.8743, 2)
  expect(view.zoom).toBeGreaterThan(15.5)
  await expect(page.locator('.maplibregl-ctrl-attrib')).toContainText('OpenStreetMap')
  await expect(page.getByTestId('basemap-switcher')).toContainText('OSM')
})

test('all basemaps switch without errors and keep selection, uploads, results, terrain and extrusions', async ({ page }) => {
  await page.goto('/')
  await waitForMap(page)
  await drawRectangle(page, [360, 300], [700, 600])
  await page.getByTestId('upload-input').setInputFiles([
    { name: 'points.csv', mimeType: 'text/csv', buffer: Buffer.from('name,lat,lon\nA,49.874,8.659\nB,49.875,8.661\n') },
  ])
  await ask(page, 'Show all schools in the selected area.')
  await page.getByTestId('view-mode-toggle').click()
  await page.waitForFunction(() => window.__geoMap!.getPitch() > 55 && !window.__geoMap!.isMoving())

  for (const id of ['official', 'light', 'relief', 'aerial', 'osm']) {
    await page.getByTestId('basemap-switcher').click()
    await page.getByTestId(`basemap-${id}`).click()
    await expect(page).toHaveURL(id === 'osm' ? /^(?!.*basemap=)/ : new RegExp(`basemap=${id}`))
    await page.waitForFunction(() => !document.querySelector('[data-testid=basemap-switcher] .animate-spin'), null, { timeout: 30_000 })
    await waitForIdle(page)
    const state = await page.evaluate(() => {
      const map = window.__geoMap!
      const ids = map.getLayersOrder()
      return {
        result: ids.some((i) => i.startsWith('gt-geojson-result-')),
        upload: ids.some((i) => i.startsWith('gt-geojson-upload-')),
        selectionOnTop: ids.at(-1)?.startsWith('gt-selection') ?? false,
        terrain: map.getTerrain()?.source ?? null,
        buildings: map.getLayer('gt-buildings') ? map.getLayoutProperty('gt-buildings', 'visibility') : null,
      }
    })
    expect(state, `overlays after switching to ${id}`).toEqual({
      result: true,
      upload: true,
      selectionOnTop: true,
      terrain: 'gt-dem-terrain',
      buildings: 'visible',
    })
    await expect(page.locator('.maplibregl-ctrl-attrib')).not.toBeEmpty()
    if (id === 'aerial') await expect(page.locator('.maplibregl-ctrl-attrib')).toContainText('Hessische Verwaltung')
  }
})

test('3D shows terrain and extruded buildings; 2D returns to a flat top-down view', async ({ page }) => {
  await page.goto('/')
  await waitForMap(page)

  await page.getByTestId('view-mode-toggle').click()
  await page.waitForFunction(() => window.__geoMap!.getPitch() > 55 && !window.__geoMap!.isMoving())
  await waitForIdle(page)
  const threeD = await page.evaluate(() => ({
    terrain: window.__geoMap!.getTerrain()?.source,
    buildings: window.__geoMap!.queryRenderedFeatures({ layers: ['gt-buildings'] }).length,
  }))
  expect(threeD.terrain).toBe('gt-dem-terrain')
  expect(threeD.buildings).toBeGreaterThan(0)

  await page.getByTestId('view-mode-toggle').click()
  await page.waitForFunction(() => window.__geoMap!.getPitch() === 0 && !window.__geoMap!.isMoving())
  expect(await page.evaluate(() => window.__geoMap!.getTerrain())).toBeNull()
})

test('search finds Fraunhofer IGD Darmstadt and Kölner Dom and flies there', async ({ page }) => {
  await page.goto('/')
  await waitForMap(page)
  const search = page.getByRole('combobox', { name: 'Search places' })

  await search.fill('Fraunhofer IGD Darmstadt')
  await expect(page.getByRole('option', { name: /Fraunhofer IGD/ })).toBeVisible()
  await search.fill('Kölner Dom')
  await page.getByRole('option', { name: /Kölner Dom/ }).click()
  await page.waitForFunction(() => Math.abs(window.__geoMap!.getCenter().lng - 6.958) < 0.01 && !window.__geoMap!.isMoving(), null, { timeout: 15_000 })
})

test('rectangle and polygon selections show their area; clear removes them', async ({ page }) => {
  await page.goto('/')
  await waitForMap(page)

  await drawRectangle(page, [350, 300], [650, 550])
  await expect(page.getByTestId('selection-chip')).toContainText(/Rectangle, [\d,.]+ (m²|km²)/)

  await page.getByTestId('draw-polygon').click()
  for (const [x, y] of [[420, 320], [620, 340], [600, 520], [430, 500]]) await page.mouse.click(x, y)
  await page.mouse.click(420, 320)
  await expect(page.getByTestId('selection-chip')).toContainText(/Polygon, [\d,.]+ (m²|km²)/)

  await page.getByTestId('draw-clear').click()
  await expect(page.getByTestId('selection-chip')).toHaveCount(0)
  expect(await page.evaluate(() => window.__geoMap!.getLayer('gt-selection-line'))).toBeUndefined()
})

test('GeoJSON and CSV uploads render as layers with popups and context chips', async ({ page }) => {
  await page.goto('/')
  await waitForMap(page)

  await page.getByTestId('upload-input').setInputFiles([
    { name: 'parks.geojson', mimeType: 'application/geo+json', buffer: Buffer.from(JSON.stringify({ type: 'FeatureCollection', features: [{ type: 'Feature', properties: { name: 'Herrngarten' }, geometry: { type: 'Polygon', coordinates: [[[8.653, 49.877], [8.657, 49.877], [8.657, 49.88], [8.653, 49.88], [8.653, 49.877]]] } }] })) },
    { name: 'ladepunkte.csv', mimeType: 'text/csv', buffer: Buffer.from('Name;Breite;Länge;kW\nIGD;49,87425;8,65989;22\nLuisenplatz;49,8728;8,6512;50\n') },
  ])
  const context = page.getByRole('group', { name: 'Context for your question' })
  await expect(context).toContainText('parks.geojson, 1 feature')
  await expect(context).toContainText('ladepunkte.csv, 2 features')

  await page.evaluate(() => window.__geoMap!.jumpTo({ center: [8.65989, 49.87425], zoom: 16 }))
  await waitForIdle(page)
  const point = await page.evaluate(() => window.__geoMap!.project([8.65989, 49.87425]))
  const box = (await page.getByTestId('map').boundingBox())!
  await page.mouse.click(box.x + point.x, box.y + point.y)
  await expect(page.locator('.gt-popup')).toContainText('IGD')
  await expect(page.locator('.gt-popup')).toContainText('kW')
})

test('mock conversations in English and German stream steps, text and sources and add a Demo data layer', async ({ page }) => {
  await page.goto('/')
  await waitForMap(page)
  await drawRectangle(page, [300, 260], [700, 600])

  await ask(page, 'Where could new EV chargers go in this area?')
  const english = page.getByTestId('assistant-message').last()
  await expect(english.getByTestId('tool-steps')).toContainText('Searching OpenStreetMap for parking areas')
  await expect(english).toContainText('demo data')
  await expect(english.getByRole('link', { name: /OpenStreetMap/ })).toBeVisible()
  await page.getByTestId('layers-button').click()
  await expect(page.getByRole('region', { name: 'Agent results' })).toContainText('EV charging candidates (Demo data)')
  await page.getByTestId('layers-button').click()

  await page.getByRole('radio', { name: 'Deutsch' }).click()
  await ask(page, 'Wo könnten in diesem Gebiet neue Ladesäulen hin?')
  const german = page.getByTestId('assistant-message').last()
  await expect(german.getByTestId('tool-steps')).toContainText('OpenStreetMap nach Parkplätzen durchsuchen')
  await expect(german).toContainText('Demo-Daten')

  await page.evaluate(() => window.__geoMap!.jumpTo({ center: [7.0, 51.0], zoom: 8 }))
  await german.getByRole('button', { name: 'Auf Ergebnisse zoomen' }).click()
  await page.waitForFunction(() => window.__geoMap!.getZoom() > 14 && !window.__geoMap!.isMoving(), null, { timeout: 15_000 })
})

test('the chat panel resizes, collapses and widens', async ({ page }) => {
  await page.goto('/')
  await waitForMap(page)
  const width = () => page.getByTestId('chat-panel').evaluate((el) => el.getBoundingClientRect().width)
  const start = await width()

  const handle = (await page.locator('[role=separator]').boundingBox())!
  await page.mouse.move(handle.x + 1, 450)
  await page.mouse.down()
  await page.mouse.move(handle.x - 150, 450, { steps: 8 })
  await page.mouse.up()
  expect(await width()).toBeGreaterThan(start + 100)

  await page.getByRole('button', { name: 'Widen chat' }).click()
  await expect.poll(width).toBeGreaterThan(1440 * 0.55)
  await page.getByRole('button', { name: 'Hide chat' }).click()
  await expect(page.getByTestId('chat-fab')).toBeVisible()
  await page.getByTestId('chat-fab').click()
  await expect(page.getByTestId('chat-panel')).toBeVisible()
})

test('the EN/DE toggle switches the UI text and persists', async ({ page }) => {
  await page.goto('/')
  await waitForMap(page)
  await page.getByRole('radio', { name: 'Deutsch' }).click()

  await expect(page.getByRole('combobox', { name: 'Orte suchen' })).toHaveAttribute('placeholder', 'Orte in Deutschland suchen')
  await expect(page.getByRole('heading', { name: 'Geo-Assistent' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Zeig alle Schulen im markierten Bereich.' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Rechteck zeichnen' })).toBeVisible()
  await expect(page.locator('html')).toHaveAttribute('lang', 'de')

  await page.reload()
  await waitForMap(page)
  await expect(page.getByRole('heading', { name: 'Geo-Assistent' })).toBeVisible()
})

test.describe('phone', () => {
  test.use({ viewport: { width: 390, height: 844 } })

  test('the bottom sheet snaps between peek, half and full, and the map stays usable', async ({ page }) => {
    await page.goto('/')
    await waitForMap(page)
    const sheet = page.getByTestId('bottom-sheet')
    await expect(sheet).toHaveAttribute('data-snap', 'peek')

    await ask(page, 'Show all schools in the selected area.')
    await expect(sheet).toHaveAttribute('data-snap', 'half')
    await page.getByRole('button', { name: 'Drag to resize the chat' }).click()
    await expect(sheet).toHaveAttribute('data-snap', 'full')
    await page.getByRole('button', { name: 'Drag to resize the chat' }).click()
    await expect(sheet).toHaveAttribute('data-snap', 'peek')
    await expect(page.getByTestId('search-box')).toBeVisible()
    expect(await resultLayerIds(page)).not.toHaveLength(0)
  })
})
