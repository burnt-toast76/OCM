// SPDX-License-Identifier: AGPL-3.0-or-later
// UI convenience only -- proposes a nicer default pose before it's sent
// to place_instance/move_instance. NOT a rule: the server is still the
// only authority on whether a pose is actually acceptable (workspace
// bounds, tool-slot occupancy, ...); snapping here can't make an invalid
// placement valid, and disabling it (the free-placement modifier) can't
// make a valid one invalid.

export const GRID_MM = 125;
export const ROTATION_STEP_DEG = 90;

export function snapToGrid(mm: number, gridMm = GRID_MM): number {
  return Math.round(mm / gridMm) * gridMm;
}

export function snapRotation(deg: number, stepDeg = ROTATION_STEP_DEG): number {
  return Math.round(deg / stepDeg) * stepDeg;
}

export function normalizeDeg(deg: number): number {
  const wrapped = deg % 360;
  return wrapped < 0 ? wrapped + 360 : wrapped;
}
