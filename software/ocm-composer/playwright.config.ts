// SPDX-License-Identifier: AGPL-3.0-or-later
import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: "list",
  use: {
    baseURL: "http://localhost:5173",
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
      command: "node tests/e2e/setup-fixture.mjs && python -m ocm_api.http_app --repo .e2e-fixture --port 8000",
      url: "http://127.0.0.1:8000/list_cells",
      reuseExistingServer: !process.env.CI,
      timeout: 30_000,
    },
    {
      command: "npm run dev",
      url: "http://localhost:5173/composer/",
      reuseExistingServer: !process.env.CI,
      timeout: 30_000,
    },
  ],
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
