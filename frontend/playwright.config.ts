import { defineConfig, devices } from '@playwright/test'

/**
 * E2E smoke tests, screenshots (frontend/screenshots) and basemap thumbnails. Playwright starts its own backend
 * (port 8001, MOCK_FAST=1) and Vite (port 5174), so it never touches the dev servers of `make dev`.
 * Headless WebGL uses SwiftShader (software rendering).
 */
const BACKEND = 'http://127.0.0.1:8001'
const FRONTEND = 'http://127.0.0.1:5174'

export default defineConfig({
  testDir: './e2e',
  timeout: 90_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [['list']],
  use: {
    ...devices['Desktop Chrome'],
    baseURL: FRONTEND,
    viewport: { width: 1440, height: 900 },
    launchOptions: { args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] },
  },
  projects: [
    { name: 'e2e', testMatch: /(smoke|a11y)\.spec\.ts/ },
    { name: 'screenshots', testMatch: /screenshots\.spec\.ts/ },
    { name: 'thumbnails', testMatch: /thumbnails\.spec\.ts/ },
  ],
  webServer: [
    {
      command: 'uv run uvicorn app.main:app --host 127.0.0.1 --port 8001',
      cwd: '../backend',
      url: `${BACKEND}/api/health`,
      env: { MOCK_FAST: '1', AGENT_MODE: 'mock' },
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
    {
      command: 'npx vite --host 127.0.0.1 --port 5174 --strictPort',
      url: FRONTEND,
      env: { BACKEND_URL: BACKEND },
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
  ],
})
