// SPDX-License-Identifier: AGPL-3.0-or-later
// Regression test for the drag rewrite: the instance is client-authoritative
// for the whole drag (no mid-drag move_instance calls) and commits with a
// single call on drop. Drags feed1 exactly 3 grid cells and asserts the
// rendered/confirmed position lands exactly on the computed drop target
// once the single API round-trip settles -- not approximately, not off by
// a snap increment.

import { test, expect } from "@playwright/test";

declare global {
  interface Window {
    __ocmComposerTestHooks?: {
      getInstanceScreenXY(instance: string): { x: number; y: number } | null;
      worldToScreenXY(xMm: number, yMm: number, zMm: number): { x: number; y: number } | null;
      getInstancePoseMm(instance: string): [number, number, number] | null;
    };
  }
}

const GRID_MM = 125;
const snapToGrid = (mm: number) => Math.round(mm / GRID_MM) * GRID_MM;

test("dragging an instance 3 grid cells lands exactly on the drop position", async ({ page }) => {
  await page.goto("/composer/");

  await page.waitForSelector('#cell-select option[value="bracket-asm-01"]', { state: "attached" });
  await page.selectOption("#cell-select", "bracket-asm-01");
  await expect(page.getByRole("button", { name: "feed1" })).toBeVisible();

  await expect
    .poll(() => page.evaluate(() => window.__ocmComposerTestHooks?.getInstancePoseMm("feed1") ?? null), {
      message: "the test hook should report feed1's starting pose once the cell has loaded",
    })
    .not.toBeNull();

  const startMm = await page.evaluate(() => window.__ocmComposerTestHooks!.getInstancePoseMm("feed1")!);
  // Snapped, not the raw starting value -- the first pointermove of the
  // drag snaps to the grid too, so the reachable target is 3 cells from
  // the SNAPPED start, not from a possibly-off-grid starting pose.
  const targetMm: [number, number, number] = [snapToGrid(startMm[0]) + 3 * GRID_MM, snapToGrid(startMm[1]), startMm[2]];

  await expect
    .poll(() => page.evaluate(() => window.__ocmComposerTestHooks?.getInstanceScreenXY("feed1") ?? null), {
      message: "the test hook should locate feed1 on screen once the canvas has rendered",
    })
    .not.toBeNull();
  const start = await page.evaluate(() => window.__ocmComposerTestHooks!.getInstanceScreenXY("feed1")!);

  // Don't trust an ABSOLUTE worldToScreenXY(targetMm) as the drop pixel:
  // getInstanceScreenXY projects the instance's visual PRIMITIVE geometry,
  // which can be offset from its own mount origin (feed1's collision box
  // isn't necessarily centered on its mount frame) -- an absolute target
  // computed in the "pure mount-origin" basis doesn't line up with a click
  // point computed in the "primitive" basis. Apply the pure mount-origin
  // DELTA on top of wherever we actually clicked instead; the delta
  // cancels any fixed offset the same way DraggableInstance's own
  // ray-plane math does.
  const [worldStart, worldTarget] = await Promise.all([
    page.evaluate(([x, y, z]) => window.__ocmComposerTestHooks!.worldToScreenXY(x, y, z)!, startMm),
    page.evaluate(([x, y, z]) => window.__ocmComposerTestHooks!.worldToScreenXY(x, y, z)!, targetMm),
  ]);
  const target = { x: start.x + (worldTarget.x - worldStart.x), y: start.y + (worldTarget.y - worldStart.y) };

  await page.mouse.move(start.x, start.y);
  await page.mouse.down();
  await page.mouse.move(target.x, target.y, { steps: 10 });
  await page.mouse.up();

  // The single drop commit's round trip settling is the only thing this
  // waits on -- well within bounds, so no refusal is expected.
  await expect
    .poll(() => page.evaluate(() => window.__ocmComposerTestHooks!.getInstancePoseMm("feed1")), { timeout: 10_000 })
    .toEqual(targetMm);

  await expect(page.locator(".toast")).toHaveCount(0);
});
