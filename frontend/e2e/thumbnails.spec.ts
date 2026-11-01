import { test } from '@playwright/test'
import { waitForMap } from './helpers'

/**
 * Generates the basemap previews of the switcher (public/basemaps/<id>.jpg) from the real styles over Darmstadt.
 * Run with `npx playwright test --project=thumbnails`. While basemap.de is unreachable, Official/Light/Relief show
 * their OpenFreeMap fallbacks; re-run when BKG is back.
 */
const VIEWS = {
  osm: '15.4/49.8735/8.6530',
  official: '15.4/49.8735/8.6530',
  light: '15.4/49.8735/8.6530',
  // Hills east of Darmstadt, so the relief preview actually shows relief.
  relief: '12.6/49.8020/8.7750',
  aerial: '16.2/49.87425/8.65989',
} as const

for (const [id, view] of Object.entries(VIEWS)) {
  test(`thumbnail ${id}`, async ({ page }) => {
    await page.goto(`/#map=${view}&basemap=${id}`)
    await waitForMap(page)
    await page.addStyleTag({ content: 'main > :not([data-testid=map]) { visibility: hidden !important } .maplibregl-control-container { display: none }' })
    const box = (await page.getByTestId('map').boundingBox())!
    const size = 96
    await page.screenshot({
      path: `public/basemaps/${id}.jpg`,
      type: 'jpeg',
      quality: 82,
      clip: { x: box.x + box.width / 2 - size / 2, y: box.y + box.height / 2 - size / 2, width: size, height: size },
    })
  })
}
