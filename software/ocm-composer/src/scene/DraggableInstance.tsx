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
// synthetic event system -- e.stopPropagation() here does NOT reach it at
// all, so it happily orbits/pans at the same time as a drag unless
// something disables it explicitly. Two layers do that: SceneCanvas
// drives OrbitControls' `enabled` prop off the store's `dragging` flag
// (reactive, but waits on a React render), and -- because that's not
// synchronous enough to beat the very first native pointermove of a fast
// drag -- handlePointerDown here ALSO reaches into the live controls
// instance (via useThree's `controls`, populated by OrbitControls'
// `makeDefault`) and flips `.enabled` directly, before React re-renders
// at all. Every exit from a drag (pointer-up, pointer-cancel, or losing
// pointer capture -- e.g. an OS-level gesture reasserting it elsewhere --
// must re-enable both, or orbit stays dead for the rest of the session.

import { useCallback, useRef, useState } from "react";
import { useThree } from "@react-three/fiber";
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
  const clearGhost = useComposerStore((s) => s.clearGhost);
  const controls = useThree((s) => s.controls) as { enabled: boolean } | null;
  const [offsetM, setOffsetM] = useState<[number, number]>([0, 0]);
  const dragRef = useRef<DragStart | null>(null);
  const draggedRef = useRef(false);

  const pose = mountEntry?.mount?.pose;
  const draggable = pose !== undefined;

  const endDrag = useCallback(() => {
    dragRef.current = null;
    draggedRef.current = false;
    if (controls) controls.enabled = true;
    useComposerStore.getState().setDragging(false);
  }, [controls]);

  const handlePointerDown = useCallback(
    (e: ThreeEvent<PointerEvent>) => {
      draggedRef.current = false;
      if (!draggable || !pose) {
        // TEMP DIAGNOSTIC (remove once the still-rotates report is root-caused):
        // confirms whether this instance's own pointerdown fired at all, and
        // if so, why it bailed before disabling OrbitControls.
        // eslint-disable-next-line no-console
        console.debug("[ocm-composer] drag: pointerdown on", instance, "but not draggable (pose:", pose, ")");
        return;
      }
      e.stopPropagation();
      // eslint-disable-next-line no-console
      console.debug("[ocm-composer] drag: pointerdown HIT", instance, "-- disabling orbit controls now. controls present:", !!controls);
      // Synchronous, before React re-renders -- see the module docstring.
      if (controls) controls.enabled = false;
      useComposerStore.getState().setDragging(true);
      (e.target as Element).setPointerCapture?.(e.pointerId);
      const point = intersectGroundPlane(e.ray, pose.xyz_mm[2]);
      if (!point) {
        // Camera angle grazes the horizon right at this pixel -- bail, no
        // drag starts. Undo the disable immediately; nothing else will.
        endDrag();
        return;
      }
      dragRef.current = { worldX: point.x, worldY: point.y, xMm: pose.xyz_mm[0], yMm: pose.xyz_mm[1], zMm: pose.xyz_mm[2] };
      clearGhost(); // a fresh drag attempt supersedes any stale refusal ghost from a previous one
    },
    [draggable, pose, controls, clearGhost, endDrag],
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
      const resolved = resolveDragXY(e.ray, drag, !e.shiftKey);
      endDrag();
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
    [instance, pose, moveExistingInstance, onSelect, endDrag, suppressNextClickRef],
  );

  // Both required: onPointerCancel covers an OS-level gesture cancel;
  // onLostPointerCapture covers capture being reassigned/released out
  // from under the drag by other means (e.g. another element stealing
  // it). Either one, left unhandled, leaves controls.enabled=false (and
  // the store's dragging=true) stuck forever -- orbit dead for the rest
  // of the session.
  const handleInterruptedDrag = useCallback(() => {
    if (!dragRef.current) return;
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
      onPointerCancel={handleInterruptedDrag}
      onLostPointerCapture={handleInterruptedDrag}
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
