import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright E2E config for the 6thSense marketing frontend.
 *
 * The app is a static Vite SPA (see package.json: `dev` / `build` / `preview`).
 * These specs run against the PRODUCTION build served by `vite preview`, so we
 * exercise the same bundle real visitors get — the SEO prerender shell strip,
 * the manualChunks split, and lazy route loading all behave as in prod.
 *
 * Forms POST to `${VITE_API_URL}/api/leads`. The specs never require a live
 * backend: each test intercepts `**\/api/leads` with `page.route` so it can both
 * (a) run offline and (b) assert the exact payload (`kind`, `product`, …) the
 * client sends. That payload assertion is the whole point of the critical
 * waitlist regression test.
 *
 * Three viewport projects (375 / 768 / 1280) run every spec so mobile, tablet,
 * and desktop layouts are all covered.
 */

// The three required viewports. Named so reports read e.g. "mobile-375 › …".
const VIEWPORTS = [
  { name: "mobile-375", width: 375, height: 812 },
  { name: "tablet-768", width: 768, height: 1024 },
  { name: "desktop-1280", width: 1280, height: 900 },
];

// Where `vite preview` serves the built site. Overridable so CI can point the
// same specs at a deployed preview URL instead of booting a local server.
const PORT = Number(process.env.E2E_PORT ?? 4173);
const BASE_URL = process.env.E2E_BASE_URL ?? `http://localhost:${PORT}`;

// When an external BASE_URL is supplied we don't manage a server.
const useLocalServer = !process.env.E2E_BASE_URL;

export default defineConfig({
  testDir: "./tests/e2e",
  // Fail the run if a spec is accidentally left with `test.only`.
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["github"], ["list"]] : "list",
  // A slow first build + lazy chunk load shouldn't flake the suite.
  timeout: 30_000,
  expect: { timeout: 10_000 },

  use: {
    baseURL: BASE_URL,
    trace: "on-first-retry",
    // Give every test a chance to fail loudly if the app can't be reached.
    actionTimeout: 10_000,
  },

  projects: VIEWPORTS.map((vp) => ({
    name: vp.name,
    use: {
      ...devices["Desktop Chrome"],
      viewport: { width: vp.width, height: vp.height },
    },
  })),

  // Build once, then serve the built bundle. `reuseExistingServer` locally lets
  // a dev keep a preview running between runs. Skipped entirely when an external
  // E2E_BASE_URL is provided.
  webServer: useLocalServer
    ? {
        command: `npm run build && npm run preview -- --port ${PORT} --strictPort`,
        url: BASE_URL,
        reuseExistingServer: !process.env.CI,
        timeout: 120_000,
        stdout: "pipe",
        stderr: "pipe",
      }
    : undefined,
});
