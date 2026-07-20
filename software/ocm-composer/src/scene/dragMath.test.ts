// SPDX-License-Identifier: AGPL-3.0-or-later
// Pure ray/plane math -- no React, no Three.js canvas needed, just
// constructed THREE.Ray objects. Pins down the two properties the drag
// bugfix depends on: the plane sits at the DRAG's own starting height (not
// always world z=0), and a ray that misses the plane returns null instead
// of a garbage (0,0,0) intersection.

import { describe, expect, it } from "vitest";
import * as THREE from "three";
import { GRID_MM } from "./snap";
import { intersectGroundPlane, resolveDragXY } from "./dragMath";
import type { DragStart } from "./dragMath";

// A ray straight down the -Z axis from (x, y, 10) always hits any
// horizontal plane at world (x, y, planeZ) regardless of planeZ -- the
// simplest way to construct a deterministic intersection for a test.
function verticalRayAt(xM: number, yM: number): THREE.Ray {
  return new THREE.Ray(new THREE.Vector3(xM, yM, 10), new THREE.Vector3(0, 0, -1));
}

describe("intersectGroundPlane", () => {
  it("hits the plane at the requested height, not always z=0", () => {
    const point = intersectGroundPlane(verticalRayAt(1, 2), 500 /* mm */);
    expect(point).not.toBeNull();
    expect(point!.x).toBeCloseTo(1);
    expect(point!.y).toBeCloseTo(2);
    expect(point!.z).toBeCloseTo(0.5); // 500mm -> 0.5m
  });

  it("returns null, not a (0,0,0) point, when the ray is parallel to the plane", () => {
    const horizontalRay = new THREE.Ray(new THREE.Vector3(0, 0, 1), new THREE.Vector3(1, 0, 0));
    expect(intersectGroundPlane(horizontalRay, 0)).toBeNull();
  });
});

describe("resolveDragXY", () => {
  const drag: DragStart = { worldX: 0, worldY: 0, xMm: 180, yMm: 640, zMm: 0 };

  it("adds the ray/plane delta to the drag's starting mm position", () => {
    const resolved = resolveDragXY(verticalRayAt(0.375, 0), drag, false);
    expect(resolved).not.toBeNull();
    const [xMm, yMm] = resolved!;
    expect(xMm).toBeCloseTo(180 + 375);
    expect(yMm).toBeCloseTo(640);
  });

  it("snaps the result to the grid when asked", () => {
    // 0.4m = +400mm from start -> 580mm, nearest 125mm multiple is 625mm.
    const [xMm] = resolveDragXY(verticalRayAt(0.4, 0), drag, true)!;
    expect(xMm % GRID_MM).toBe(0);
    expect(xMm).toBe(625);
  });

  it("uses the drag's own starting z for the plane, not world z=0", () => {
    const elevatedDrag: DragStart = { worldX: 0, worldY: 0, xMm: 0, yMm: 0, zMm: 300 };
    // A ray that only intersects a plane at z=0.3m (300mm) -- if this drag
    // wrongly raycast against world z=0 it would resolve to a different
    // (wrong) XY, since the ray isn't vertical.
    const ray = new THREE.Ray(new THREE.Vector3(0, 0, 0.6), new THREE.Vector3(0.1, 0, -1).normalize());
    const resolved = resolveDragXY(ray, elevatedDrag, false);
    expect(resolved).not.toBeNull();
    // At z=0.3 the ray has traveled half its z-extent (0.6 -> 0.3), so x
    // has moved by half of its slope too: 0.1/1 * 0.3 = 0.03m = 30mm.
    const [xMm] = resolved!;
    expect(xMm).toBeCloseTo(30, 0);
  });

  it("returns null instead of jumping the instance when the pointer grazes the horizon", () => {
    // Origin off the plane (z=1, plane at z=0) and a direction parallel to
    // it -- a genuine miss, not the degenerate "origin sits on the plane"
    // case (which THREE.Ray legitimately treats as an intersection at
    // distance 0).
    const grazingRay = new THREE.Ray(new THREE.Vector3(0, 0, 1), new THREE.Vector3(1, 0, 0));
    expect(resolveDragXY(grazingRay, drag, false)).toBeNull();
  });
});
