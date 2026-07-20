// SPDX-License-Identifier: AGPL-3.0-or-later
// Regression test for the drag rewrite. Two things must both hold after a
// drag: the instance is client-authoritative for the whole drag (no
// mid-drag move_instance calls) and commits with a single call on drop,
// landing exactly on the computed drop target -- AND the camera must not
// have moved at all, which is the actual regression this test exists to
// catch: OrbitControls listens on the canvas with its own native
// listeners, entirely outside React/R3F's event system, so a drag that
// fails to disable it produces a WRONG final position for a subtler
// reason than off-by-a-grid-cell math -- the camera itself drifted mid-
// drag, invalidating the drag's own ray-plane reference frame. Asserting
// only the module's landed position can't distinguish "drag math is
// correct" from "drag math and a moving camera happened to cancel out";
// asserting the camera's own angles is what actually pins this down.

import { test, expect } from "@playwright/test";

declare global {
  interface Window {
    __ocmComposerTestHooks?: {
      getInstanceScreenXY(instance: string): { x: number; y: number } | null;
      worldToScreenXY(xMm: number, yMm: number, zMm: number): { x: number; y: number } | null;
      getInstancePoseMm(instance: string): [number, number, number] | null;
      getOrbitAngles(): { azimuthal: number; polar: number } | null;
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

  const anglesBefore = await page.evaluate(() => window.__ocmComposerTestHooks!.getOrbitAngles()!);
  expect(anglesBefore).not.toBeNull();

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

  // THE regression check for the OrbitControls-not-disabled bug: a whole
  // mouse-down-move-up gesture happened on the canvas, and the camera's
  // own angles must be unchanged. If OrbitControls leaked input during
  // the drag, this fails even when the module still happened to land on
  // the right mm position. toBeCloseTo, not toEqual: getAzimuthalAngle/
  // getPolarAngle re-derive the angles from the camera's matrix on every
  // call, which has ~1e-14 floating-point jitter even with zero real
  // movement -- 6 digits of precision is far tighter than any real orbit
  // drag (which moves the angle by whole fractions of a radian) while
  // comfortably absorbing that noise.
  const anglesAfter = await page.evaluate(() => window.__ocmComposerTestHooks!.getOrbitAngles()!);
  expect(anglesAfter.azimuthal).toBeCloseTo(anglesBefore.azimuthal, 6);
  expect(anglesAfter.polar).toBeCloseTo(anglesBefore.polar, 6);
});
