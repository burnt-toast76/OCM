// SPDX-License-Identifier: AGPL-3.0-or-later
import { defineConfig, devices } from "@playwright/test";

// Overridable, same pattern as vite.config.ts's own OCM_API_URL -- lets
// the e2e suite run on alternate ports when 8000/5173 are already taken
// by an unrelated dev session (a real backend against the REAL working
// tree on the default port is exactly what setup-fixture.mjs's own
// throwaway-fixture discipline exists to never touch).
const BACKEND_PORT = process.env.OCM_TEST_BACKEND_PORT ?? "8000";
const FRONTEND_PORT = process.env.OCM_TEST_FRONTEND_PORT ?? "5173";

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: false,
  // All spec files share one backend fixture (see setup-fixture.mjs) and
  // some touch the same instance (feed1) in bracket-asm-01 -- running
  // spec FILES in parallel workers would race on that shared cell.yaml.
  // The suite is small enough that serializing it costs nothing real.
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: "list",
  use: {
    baseURL: `http://localhost:${FRONTEND_PORT}`,
    trace: "retain-on-failure",
    // The 3D scene's camera framing (and thus how many screen pixels a
    // given world-space drag covers) depends on viewport aspect ratio.
    // Chromium's Playwright default (1280x720) frames the deck too
    // tightly for a screen-space drag to reliably cross the workspace
    // boundary; this size is confirmed (via manual testing) to give the
    // feeder enough room to actually go out of bounds.
    viewport: { width: 1400, height: 900 },
  },
  // ADR-0012: the composer under test is a pure client of ocm-api-http --
  // both the backend and the Vite dev server (which proxies to it, same
  // as production's single-origin /composer mount) spin up together.
  webServer: [
    {
      command: `node tests/e2e/setup-fixture.mjs && python -m ocm_api.http_app --repo .e2e-fixture --port ${BACKEND_PORT}`,
      url: `http://127.0.0.1:${BACKEND_PORT}/list_cells`,
      reuseExistingServer: !process.env.CI,
      timeout: 30_000,
    },
    {
      command: `npm run dev -- --port ${FRONTEND_PORT} --strictPort`,
      url: `http://localhost:${FRONTEND_PORT}/composer/`,
      env: { OCM_API_URL: `http://127.0.0.1:${BACKEND_PORT}` },
      reuseExistingServer: !process.env.CI,
      timeout: 30_000,
    },
  ],
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
