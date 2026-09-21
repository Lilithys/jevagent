import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir: './tests/e2e',
  timeout: 60000,
  fullyParallel: false,
  workers: 1,
  expect: { timeout: 15000 },
  reporter: 'list',
  use: {
    baseURL: 'http://127.0.0.1:3211',
    channel: process.env.BROWSER_CHANNEL || 'chrome',
    headless: true,
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
    viewport: { width: 1440, height: 1000 },
  },
  webServer: {
    command: `PORT=3211 DATA_DIR=./data/e2e/run-${Date.now()} TYPESAFE_API_KEY= BROWSER_STORAGE_STATE= npm run dev`,
    url: 'http://127.0.0.1:3211/api/health',
    reuseExistingServer: false,
    timeout: 30000,
  },
});
