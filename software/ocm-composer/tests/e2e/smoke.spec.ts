// SPDX-License-Identifier: AGPL-3.0-or-later
// The one required e2e smoke test: load the real bracket-asm-01 cell,
// drag its feeder out of the workspace, and confirm the refusal toast
// carries the engine's own overhang message verbatim -- not a paraphrase,
// not a generic "invalid placement" string. Runs against a throwaway
// fixture copy of the repo (see setup-fixture.mjs), never the real
// working tree.

import { test, expect } from "@playwright/test";

declare global {
  interface Window {
    __ocmComposerTestHooks?: {
      getInstanceScreenXY(instance: string): { x: number; y: number } | null;
    };
  }
}

test("dragging the feeder out of bounds shows the engine's own overhang refusal", async ({ page }) => {
  await page.goto("/composer/");

  await page.waitForSelector('#cell-select option[value="bracket-asm-01"]', { state: "attached" });
  await page.selectOption("#cell-select", "bracket-asm-01");

  // The sidebar populating is the signal the scene DATA loaded; the
  // canvas itself still needs at least one paint before the test hook's
  // camera projection is meaningful, so poll rather than read it once.
  await expect(page.getByRole("button", { name: "feed1" })).toBeVisible();

  await expect
    .poll(() => page.evaluate(() => window.__ocmComposerTestHooks?.getInstanceScreenXY("feed1") ?? null), {
      message: "the test hook should locate feed1 on screen once the canvas has rendered",
    })
    .not.toBeNull();
  const start = await page.evaluate(() => window.__ocmComposerTestHooks!.getInstanceScreenXY("feed1")!);

  // A large, PURELY HORIZONTAL screen-space drag -- more than enough to
  // push a 1200x900mm deck's feeder past the workspace footprint.
  // Deliberately dy=0: the camera looks down the ground plane at an
  // angle, so a drag with any significant upward (negative-dy) component
  // can approach the horizon, where the pointer ray stops intersecting
  // the ground plane at all (dragMath.ts's resolveDragXY correctly
  // returns null rather than a garbage position) -- DraggableInstance
  // then has no final pose to commit, so nothing happens. Horizontal
  // stays well clear of that, and empirically clears the boundary
  // cleanly once the drag is client-authoritative (a single commit on
  // drop, no more mid-drag calls to accumulate queuing latency behind).
  await page.mouse.move(start!.x, start!.y);
  await page.mouse.down();
  await page.mouse.move(start!.x + 900, start!.y, { steps: 10 });
  await page.mouse.up();

  const toast = page.locator(".toast", { hasText: "OCM_WORKSPACE_OVERHANG" });
  await expect(toast).toBeVisible({ timeout: 10_000 });

  const toastText = await toast.innerText();
  expect(toastText).toContain("feed1");
  expect(toastText).toContain("workspace footprint");
  // The actual overhang, in mm, from ocm_generator's own containment
  // check -- this is the number an operator needs, and it must be the
  // server's own words, not a client-side re-derivation.
  expect(toastText).toMatch(/by \d+(\.\d+)? mm/);

  // The issues panel agrees -- same refusal, same verbatim hint.
  const issue = page.locator(".issues-panel__item", { hasText: "OCM_WORKSPACE_OVERHANG" });
  await expect(issue).toBeVisible();
  await expect(issue).toContainText("Move feed1 inside the base footprint");
});
