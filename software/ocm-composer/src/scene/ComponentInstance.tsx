// SPDX-License-Identifier: AGPL-3.0-or-later
// One placed component instance in a module's local scene -- parallel to
// DraggableInstance.tsx (the cell composer's own drag-to-move), but
// renders a component's converted GLB (via useGLTF, GlbViewer.tsx's own
// pattern) instead of PrimitiveMesh's boxes/cylinders, and commits through
// modulesStore's moveComponentInstance (a plain update_module patch) --
// never move_instance, which is cell-specific and carries cell-specific
// refusal codes that don't apply to a component's placement inside a
// module's own local assembly scene.
//
// Copies DraggableInstance's hard-won mechanics wholesale: client-
// authoritative drag (local offset state, one commit on pointer-up), the
// two-layer OrbitControls disable (synchronous useThree-level flip at
// pointer-down, PLUS ModuleSceneCanvas's own reactive enabled={!dragging}
// -- React's re-render isn't fast enough to beat the first native
// pointermove otherwise), setPointerCapture + onPointerCancel/
// onLostPointerCapture both calling one endDrag cleanup, and the 10mm
// drag threshold. Only XY translates via drag -- rotation is authored via
// numeric rpy_deg side-panel inputs (Decisions locked in), so the group's
// own rotation is always whatever the current pose says, never touched
// mid-drag.

import { useCallback, useRef, useState } from "react";
import { useThree } from "@react-three/fiber";
import type { ThreeEvent } from "@react-three/fiber";
import { useGLTF } from "@react-three/drei";
import * as THREE from "three";
import type { ModuleComponentRow, Pose6d } from "../api/types";
import { intersectGroundPlane, resolveDragXY } from "./dragMath";
import type { DragStart } from "./dragMath";
import { useModulesStore } from "../store/modulesStore";

export interface ComponentInstanceProps {
  component: ModuleComponentRow;
  pose: Pose6d;
  glbUrl: string | null;
  suppressNextClickRef: React.MutableRefObject<boolean>;
}

const DRAG_THRESHOLD_M = 0.01; // 10mm of pointer movement before a press counts as a drag, not a click
const DEG2RAD = Math.PI / 180;

function InstanceModel({ url }: { url: string }) {
  const { scene } = useGLTF(url);
  return <primitive object={scene} />;
}

export function ComponentInstance({ component, pose, glbUrl, suppressNextClickRef }: ComponentInstanceProps) {
  const moveComponentInstance = useModulesStore((s) => s.moveComponentInstance);
  const selectComponentInstance = useModulesStore((s) => s.selectComponentInstance);
  const controls = useThree((s) => s.controls) as { enabled: boolean } | null;
  const [offsetM, setOffsetM] = useState<[number, number]>([0, 0]);
  const dragRef = useRef<DragStart | null>(null);
  const draggedRef = useRef(false);

  const endDrag = useCallback(() => {
    dragRef.current = null;
    draggedRef.current = false;
    if (controls) controls.enabled = true;
    useModulesStore.getState().setDragging(false);
  }, [controls]);

  const handlePointerDown = useCallback(
    (e: ThreeEvent<PointerEvent>) => {
      draggedRef.current = false;
      e.stopPropagation();
      if (controls) controls.enabled = false;
      useModulesStore.getState().setDragging(true);
      (e.target as Element).setPointerCapture?.(e.pointerId);
      const point = intersectGroundPlane(e.ray, pose.xyz_mm[2]);
      if (!point) {
        endDrag();
        return;
      }
      dragRef.current = { worldX: point.x, worldY: point.y, xMm: pose.xyz_mm[0], yMm: pose.xyz_mm[1], zMm: pose.xyz_mm[2] };
    },
    [controls, endDrag, pose.xyz_mm],
  );

  const handlePointerMove = useCallback((e: ThreeEvent<PointerEvent>) => {
    const drag = dragRef.current;
    if (!drag) return;
    e.stopPropagation();
    const resolved = resolveDragXY(e.ray, drag, !e.shiftKey);
    if (!resolved) return;
    const [xMm, yMm] = resolved;
    const offset: [number, number] = [(xMm - drag.xMm) / 1000, (yMm - drag.yMm) / 1000];
    if (!draggedRef.current && Math.hypot(offset[0], offset[1]) > DRAG_THRESHOLD_M) draggedRef.current = true;
    setOffsetM(offset);
  }, []);

  const handlePointerUp = useCallback(
    (e: ThreeEvent<PointerEvent>) => {
      const drag = dragRef.current;
      if (!drag) return;
      e.stopPropagation();
      const wasRealDrag = draggedRef.current;
      if (wasRealDrag) {
        suppressNextClickRef.current = true;
      } else {
        selectComponentInstance(component.refdes);
      }
      const resolved = resolveDragXY(e.ray, drag, !e.shiftKey);
      endDrag();
      if (!resolved || !wasRealDrag) {
        setOffsetM([0, 0]);
        return;
      }
      const [xMm, yMm] = resolved;
      void moveComponentInstance(component.refdes, { xyz_mm: [xMm, yMm, drag.zMm], rpy_deg: pose.rpy_deg }).finally(() => {
        // Only reset the local offset once the move has been reconciled --
        // on success the store has already refreshed to the new confirmed
        // pose by the time this runs, so offset->0 lands exactly there
        // with no visible jump; on refusal detail was deliberately left
        // alone, so offset->0 snaps back to the last confirmed pose.
        setOffsetM([0, 0]);
      });
    },
    [component.refdes, pose.rpy_deg, moveComponentInstance, selectComponentInstance, endDrag, suppressNextClickRef],
  );

  const handleInterruptedDrag = useCallback(() => {
    if (!dragRef.current) return;
    endDrag();
    setOffsetM([0, 0]);
  }, [endDrag]);

  const [xM, yM, zM] = pose.xyz_mm.map((v) => v / 1000);
  const rotation = new THREE.Euler(pose.rpy_deg[0] * DEG2RAD, pose.rpy_deg[1] * DEG2RAD, pose.rpy_deg[2] * DEG2RAD);

  if (!glbUrl) return null; // no converted GLB for this component yet -- nothing to render (still a real, placed manifest entry)

  return (
    <group
      position={[xM + offsetM[0], yM + offsetM[1], zM]}
      rotation={rotation}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={handlePointerUp}
      onPointerCancel={handleInterruptedDrag}
      onLostPointerCapture={handleInterruptedDrag}
    >
      <InstanceModel url={glbUrl} />
    </group>
  );
}
