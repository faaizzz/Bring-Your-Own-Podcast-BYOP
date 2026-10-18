import { defineConfig } from '@playwright/test';

// The stack under test comes from `make e2e` (or CI): docker-compose.e2e.yml with mock model,
// voice and news servers. See docs/e2e.md.
export default defineConfig({
  testDir: '.',
  testMatch: '*.spec.ts',
  timeout: 5 * 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [['list'], ['html', { open: 'never' }]],
  outputDir: 'test-results',
  use: {
    baseURL: process.env.E2E_BASE_URL ?? 'http://localhost:18080',
    viewport: { width: 1280, height: 800 },
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
});
