// End-to-end tests: the console driven in a real browser against the real
// stack — Caddy, the API, the worker, PostgreSQL — as `docker compose` runs it.
//
// What they guard is the wiring no unit test sees: a login that sets the
// session cookie Caddy must pass through, a page reload that must survive on
// that cookie alone, a command that must go from a button to the database and
// back to the fiche. The stack is started outside (CI workflow, or by hand —
// see frontend/README.md); these tests only point a browser at it.
import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: '.',
  // One stack, one database: tests that write share it, so they run in order.
  workers: 1,
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  timeout: 60_000,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL: process.env.E2E_BASE_URL ?? 'https://localhost',
    // The test stack serves Caddy's own local CA (`tls internal`).
    ignoreHTTPSErrors: true,
    locale: 'fr-FR',
    timezoneId: 'Pacific/Tahiti',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome'],
        launchOptions: {
          // A browser already on the machine, when Playwright's own download
          // is not an option (sandboxed runners).
          executablePath: process.env.E2E_CHROMIUM_PATH || undefined,
        },
      },
    },
  ],
});
