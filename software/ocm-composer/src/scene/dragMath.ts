// SPDX-License-Identifier: AGPL-3.0-or-later
// Pure ray/plane math for dragging an instance across the deck (and for
// resolving a palette drop's drop point -- both go through the exact same
// intersectGroundPlane below, not two subtly different implementations).
// Deliberately framework-free: no React, no store, no API client import is
// even possible from this module, so nothing in the drag path can slip a
// network call in by accident -- that's enforced by DraggableInstance's
// wiring, not by this file, but this file makes it easy to keep that way.
//
// Always raycasts against a FIXED mathematical plane at the dragged
// instance's own starting height (never against scene meshes -- hitting a
// neighboring module gives a jumpy, geometry-dependent intersection -- and
// never via screen-space pixel-delta math, which silently breaks the
// moment the camera moves mid-drag, e.g. because OrbitControls is still
// live).

import * as THREE from "three";
import { GRID_MM, snapToGrid } from "./snap";

export interface DragStart {
  /** World-space (meters) ray/plane intersection at pointer-down. */
  worldX: number;
  worldY: number;
  /** The instance's own pose at pointer-down, mm. */
  xMm: number;
  yMm: number;
  zMm: number;
}

/** The horizontal plane at world height `zMm` (mm, converted to meters). */
export function groundPlaneAt(zMm: number): THREE.Plane {
  return new THREE.Plane(new THREE.Vector3(0, 0, 1), -(zMm / 1000));
}

/**
 * Intersects `ray` with the plane at `zMm`. Returns null (not a garbage
 * (0,0,0) point) when the ray is parallel to the plane -- grazing the
 * horizon at a shallow camera angle is a real case, not a hypothetical
 * one, and callers must be able to tell "no intersection" from "intersects
 * at the origin".
 */
export function intersectGroundPlane(ray: THREE.Ray, zMm = 0): THREE.Vector3 | null {
  const point = new THREE.Vector3();
  return ray.intersectPlane(groundPlaneAt(zMm), point) ? point : null;
}

/**
 * Resolves a pointer ray (at any moment during a drag) against the drag's
 * fixed plane, returning the proposed instance position in mm relative to
 * `drag`'s starting pose. Null propagates a missed intersection so callers
 * can just skip that event rather than snapping to a wrong position.
 */
export function resolveDragXY(ray: THREE.Ray, drag: DragStart, snap: boolean): [number, number] | null {
  const point = intersectGroundPlane(ray, drag.zMm);
  if (!point) return null;
  let xMm = drag.xMm + (point.x - drag.worldX) * 1000;
  let yMm = drag.yMm + (point.y - drag.worldY) * 1000;
  if (snap) {
    xMm = snapToGrid(xMm, GRID_MM);
    yMm = snapToGrid(yMm, GRID_MM);
  }
  return [xMm, yMm];
}
