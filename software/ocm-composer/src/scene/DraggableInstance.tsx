// SPDX-License-Identifier: AGPL-3.0-or-later
// One instance's worth of primitives, draggable on the deck (z=0 plane).
// Only mount.pose instances drag directly -- an instance mounted via
// mount.on (bolted to another instance, e.g. a tool on a robot flange)
// has no free XY position of its own to drag. Dragging updates a LOCAL
// optimistic offset immediately (so the frame rate isn't gated on the
// network) and calls move_instance debounced; pointer-up always sends one
// final, non-debounced call so the true release position is never lost
// to a pending debounce. The server is still the only authority on
// whether the resulting pose is acceptable -- this only proposes one.

import { useCallback, useRef, useState } from "react";
import * as THREE from "three";
import type { ThreeEvent } from "@react-three/fiber";
import type { RawCellModule, ScenePrimitive } from "../api/types";
import type { Highlight } from "./PrimitiveMesh";
import { PrimitiveMesh } from "./PrimitiveMesh";
import { GRID_MM, snapToGrid } from "./snap";
import { useComposerStore } from "../store/store";
import { debounce } from "../lib/debounce";

const GROUND_PLANE = new THREE.Plane(new THREE.Vector3(0, 0, 1), 0);

interface DragState {
  startWorld: THREE.Vector3;
  startXYmm: [number, number];
  zMm: number;
  rpyDeg: [number, number, number];
}

export interface DraggableInstanceProps {
  instance: string;
  primitives: ScenePrimitive[];
  color: string;
  highlight: Highlight;
  mountEntry: RawCellModule | undefined;
  onSelect: (instance: string) => void;
  /** Set true for the moment right after a real drag release, so the
   * browser's trailing "click" (fired at whatever mesh is now under the
   * cursor -- possibly a DIFFERENT instance the dragged one uncovered,
   * not the one that was actually dragged) doesn't silently re-select
   * something else. */
  suppressNextClickRef: React.MutableRefObject<boolean>;
}

const DRAG_THRESHOLD_M = 0.01; // 10mm of pointer movement before a press counts as a drag, not a click

export function DraggableInstance({ instance, primitives, color, highlight, mountEntry, onSelect, suppressNextClickRef }: DraggableInstanceProps) {
  const moveExistingInstance = useComposerStore((s) => s.moveExistingInstance);
  const [offsetM, setOffsetM] = useState<[number, number]>([0, 0]);
  const dragRef = useRef<DragState | null>(null);
  const draggedRef = useRef(false);

  const pose = mountEntry?.mount?.pose;
  const draggable = pose !== undefined;

  const debouncedMove = useRef(
    debounce((xMm: number, yMm: number, zMm: number, rpyDeg: [number, number, number]) => {
      void moveExistingInstance(instance, { pose: { xyz_mm: [xMm, yMm, zMm], rpy_deg: rpyDeg } }, false);
    }, 200),
  ).current;

  const resolveDrop = useCallback((e: ThreeEvent<PointerEvent>, drag: DragState): [number, number] => {
    const point = new THREE.Vector3();
    e.ray.intersectPlane(GROUND_PLANE, point);
    let xMm = drag.startXYmm[0] + (point.x - drag.startWorld.x) * 1000;
    let yMm = drag.startXYmm[1] + (point.y - drag.startWorld.y) * 1000;
    if (!e.shiftKey) {
      xMm = snapToGrid(xMm, GRID_MM);
      yMm = snapToGrid(yMm, GRID_MM);
    }
    return [xMm, yMm];
  }, []);

  const handlePointerDown = useCallback(
    (e: ThreeEvent<PointerEvent>) => {
      draggedRef.current = false;
      if (!draggable || !pose) return;
      e.stopPropagation();
      (e.target as Element).setPointerCapture?.(e.pointerId);
      const point = new THREE.Vector3();
      e.ray.intersectPlane(GROUND_PLANE, point);
      dragRef.current = { startWorld: point, startXYmm: [pose.xyz_mm[0], pose.xyz_mm[1]], zMm: pose.xyz_mm[2], rpyDeg: pose.rpy_deg };
    },
    [draggable, pose],
  );

  const handlePointerMove = useCallback(
    (e: ThreeEvent<PointerEvent>) => {
      const drag = dragRef.current;
      if (!drag) return;
      e.stopPropagation();
      const [xMm, yMm] = resolveDrop(e, drag);
      const offset: [number, number] = [(xMm - drag.startXYmm[0]) / 1000, (yMm - drag.startXYmm[1]) / 1000];
      if (!draggedRef.current && Math.hypot(offset[0], offset[1]) > DRAG_THRESHOLD_M) draggedRef.current = true;
      setOffsetM(offset);
      debouncedMove(xMm, yMm, drag.zMm, drag.rpyDeg);
    },
    [debouncedMove, resolveDrop],
  );

  const handlePointerUp = useCallback(
    (e: ThreeEvent<PointerEvent>) => {
      const drag = dragRef.current;
      if (!drag) {
        // No drag was ever started (e.g. mount.on instances, not
        // draggable) -- a plain click, handled by PrimitiveMesh's own
        // onClick below.
        return;
      }
      e.stopPropagation();
      if (draggedRef.current) {
        // The pointer moved enough to count as a real drag: the browser's
        // trailing "click" event fires at wherever the cursor ended up,
        // which -- now that this instance has visually moved away -- may
        // be a DIFFERENT instance underneath. Suppress just that one click
        // (handleClick itself clears the flag once it's actually checked
        // it, so this never leaks into a later, genuinely separate click).
        suppressNextClickRef.current = true;
      } else {
        onSelect(instance);
      }
      // A pending debounced call that hasn't fired yet must not be allowed
      // to land AFTER this one and overwrite its (toast-worthy) result --
      // this IS the final position.
      debouncedMove.cancel();
      const [xMm, yMm] = resolveDrop(e, drag);
      void moveExistingInstance(instance, { pose: { xyz_mm: [xMm, yMm, drag.zMm], rpy_deg: drag.rpyDeg } });
      dragRef.current = null;
      setOffsetM([0, 0]);
    },
    [instance, moveExistingInstance, resolveDrop, debouncedMove, onSelect, suppressNextClickRef],
  );

  const handleClick = useCallback(
    (name: string) => {
      if (suppressNextClickRef.current) {
        suppressNextClickRef.current = false;
        return;
      }
      onSelect(name);
    },
    [onSelect, suppressNextClickRef],
  );

  return (
    <group
      position={[offsetM[0], offsetM[1], 0]}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={handlePointerUp}
    >
      {primitives.map((p, i) => (
        // A link may carry several collision primitives (e.g. frame1200's
        // own "origin" link: deck + 4 guard walls) -- `link` alone isn't a
        // unique key.
        <PrimitiveMesh key={`${p.link}-${i}`} primitive={p} color={color} highlight={highlight} onClick={handleClick} />
      ))}
    </group>
  );
}
