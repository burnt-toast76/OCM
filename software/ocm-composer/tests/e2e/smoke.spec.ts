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

  // A large screen-space drag -- more than enough to push a 1200x900mm
  // deck's feeder past the workspace footprint regardless of the current
  // camera framing. Few steps deliberately: the camera looks down the
  // ground plane at an angle, so screen-space movement maps to a LOT of
  // world-space movement near the top of the canvas (near the horizon);
  // this also keeps the number of intermediate debounced move_instance
  // calls small, which matters because ocm-api now serializes every read
  // AND write to the same cell.yaml through one per-path lock (needed for
  // correctness -- see workspace.py) -- a drag that fires many overlapping
  // calls queues up real, measurable latency behind that lock.
  await page.mouse.move(start!.x, start!.y);
  await page.mouse.down();
  await page.mouse.move(start!.x + 700, start!.y - 650, { steps: 5 });
  await page.mouse.up();

  // Generous timeout: the final pointer-up call may be queued behind
  // several debounced in-flight calls all serialized on the same
  // per-path file lock (see above) -- worth waiting out rather than
  // shortening the drag further and losing margin on the overhang itself.
  const toast = page.locator(".toast", { hasText: "WORKSPACE_OVERHANG" });
  await expect(toast).toBeVisible({ timeout: 10_000 });

  const toastText = await toast.innerText();
  expect(toastText).toContain("feed1");
  expect(toastText).toContain("workspace footprint");
  // The actual overhang, in mm, from ocm_generator's own containment
  // check -- this is the number an operator needs, and it must be the
  // server's own words, not a client-side re-derivation.
  expect(toastText).toMatch(/by \d+(\.\d+)? mm/);

  // The issues panel agrees -- same refusal, same verbatim hint.
  const issue = page.locator(".issues-panel__item", { hasText: "WORKSPACE_OVERHANG" });
  await expect(issue).toBeVisible();
  await expect(issue).toContainText("Move feed1 inside the base footprint");
});
