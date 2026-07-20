// SPDX-License-Identifier: AGPL-3.0-or-later
// One instance's worth of primitives, draggable on the deck. Only
// mount.pose instances drag directly -- an instance mounted via mount.on
// (bolted to another instance, e.g. a tool on a robot flange) has no free
// XY position of its own to drag.
//
// The instance is CLIENT-AUTHORITATIVE for the whole drag: pointer-move
// only updates a local optimistic offset (no network call, no debounce --
// mid-drag server validation isn't needed, the ghost-on-refusal covers
// it). Exactly one move_instance call fires, on pointer-up, with the final
// pose; only then does the store reconcile with the server. A refusal
// reverts the local offset (the store deliberately doesn't refresh the
// scene on refusal, so resetting the offset snaps back to the last
// confirmed pose) and shows the red ghost + toast instead.
//
// OrbitControls listens on the canvas element directly, outside R3F's own
// synthetic event system -- e.stopPropagation() here does NOT stop it from
// also orbiting the camera during what's meant to be an instance drag.
// onDragActiveChange explicitly disables it for the duration.

import { useCallback, useRef, useState } from "react";
import type { ThreeEvent } from "@react-three/fiber";
import type { RawCellModule, ScenePrimitive } from "../api/types";
import type { Highlight } from "./PrimitiveMesh";
import { PrimitiveMesh } from "./PrimitiveMesh";
import { intersectGroundPlane, resolveDragXY } from "./dragMath";
import type { DragStart } from "./dragMath";
import { useComposerStore } from "../store/store";

export interface DraggableInstanceProps {
  instance: string;
  primitives: ScenePrimitive[];
  color: string;
  highlight: Highlight;
  mountEntry: RawCellModule | undefined;
  onSelect: (instance: string) => void;
  /** Disables/re-enables OrbitControls for the duration of a real drag. */
  onDragActiveChange: (active: boolean) => void;
  /** Set true for the moment right after a real drag release, so the
   * browser's trailing "click" (fired at whatever mesh is now under the
   * cursor -- possibly a DIFFERENT instance the dragged one uncovered,
   * not the one that was actually dragged) doesn't silently re-select
   * something else. */
  suppressNextClickRef: React.MutableRefObject<boolean>;
}

const DRAG_THRESHOLD_M = 0.01; // 10mm of pointer movement before a press counts as a drag, not a click

export function DraggableInstance({
  instance,
  primitives,
  color,
  highlight,
  mountEntry,
  onSelect,
  onDragActiveChange,
  suppressNextClickRef,
}: DraggableInstanceProps) {
  const moveExistingInstance = useComposerStore((s) => s.moveExistingInstance);
  const clearGhost = useComposerStore((s) => s.clearGhost);
  const [offsetM, setOffsetM] = useState<[number, number]>([0, 0]);
  const dragRef = useRef<DragStart | null>(null);
  const draggedRef = useRef(false);

  const pose = mountEntry?.mount?.pose;
  const draggable = pose !== undefined;

  const endDrag = useCallback(() => {
    dragRef.current = null;
    draggedRef.current = false;
    onDragActiveChange(false);
  }, [onDragActiveChange]);

  const handlePointerDown = useCallback(
    (e: ThreeEvent<PointerEvent>) => {
      draggedRef.current = false;
      if (!draggable || !pose) return;
      e.stopPropagation();
      (e.target as Element).setPointerCapture?.(e.pointerId);
      const point = intersectGroundPlane(e.ray, pose.xyz_mm[2]);
      if (!point) return; // camera angle grazes the horizon right at this pixel -- bail, no drag starts
      dragRef.current = { worldX: point.x, worldY: point.y, xMm: pose.xyz_mm[0], yMm: pose.xyz_mm[1], zMm: pose.xyz_mm[2] };
      onDragActiveChange(true);
      clearGhost(); // a fresh drag attempt supersedes any stale refusal ghost from a previous one
    },
    [draggable, pose, onDragActiveChange, clearGhost],
  );

  const handlePointerMove = useCallback(
    (e: ThreeEvent<PointerEvent>) => {
      const drag = dragRef.current;
      if (!drag) return;
      e.stopPropagation();
      const resolved = resolveDragXY(e.ray, drag, !e.shiftKey);
      if (!resolved) return; // ray missed the plane this event -- keep the last valid offset
      const [xMm, yMm] = resolved;
      const offset: [number, number] = [(xMm - drag.xMm) / 1000, (yMm - drag.yMm) / 1000];
      if (!draggedRef.current && Math.hypot(offset[0], offset[1]) > DRAG_THRESHOLD_M) draggedRef.current = true;
      setOffsetM(offset);
    },
    [],
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
      const wasRealDrag = draggedRef.current;
      if (wasRealDrag) {
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
      onDragActiveChange(false);
      const resolved = resolveDragXY(e.ray, drag, !e.shiftKey);
      dragRef.current = null;
      draggedRef.current = false;
      if (!resolved || !wasRealDrag) {
        // No real drag, or the release event itself missed the plane --
        // nothing to commit either way.
        setOffsetM([0, 0]);
        return;
      }
      const [xMm, yMm] = resolved;
      void moveExistingInstance(instance, { pose: { xyz_mm: [xMm, yMm, drag.zMm], rpy_deg: pose!.rpy_deg } }).finally(() => {
        // Only reset the local offset once the drop has been reconciled:
        // on success the store has already refreshed the scene to the new
        // confirmed pose by the time this runs, so offset->0 lands exactly
        // there with no visible jump; on refusal the scene was
        // deliberately left alone, so offset->0 snaps back to the last
        // confirmed pose -- the intended "reverted" affordance.
        setOffsetM([0, 0]);
      });
    },
    [instance, pose, moveExistingInstance, onSelect, onDragActiveChange, suppressNextClickRef],
  );

  const handlePointerCancel = useCallback(() => {
    if (!dragRef.current) return;
    // Pointer capture was lost mid-drag (e.g. an OS-level gesture cancel).
    // Abort without committing -- no move_instance call, just revert.
    endDrag();
    setOffsetM([0, 0]);
  }, [endDrag]);

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
      onPointerCancel={handlePointerCancel}
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
