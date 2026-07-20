// SPDX-License-Identifier: AGPL-3.0-or-later
// The 3D view: renders build_scene's own primitives/colors/markers
// payload with the same material rules as ocm-generator's debug HTML
// viewer (see PrimitiveMesh), handles the palette-drop-to-place and
// drag-to-move interactions, and shows the ghost/highlight for whatever
// the last refusal was. No rule logic -- every drop/drag ends in a call
// to the store's placeNewInstance/moveExistingInstance, which is the
// server's decision, not this component's.

import { useCallback, useEffect, useMemo, useRef } from "react";
import type { ComponentRef } from "react";
import { Canvas, useThree } from "@react-three/fiber";
import { OrbitControls } from "@react-three/drei";
import * as THREE from "three";
import { useComposerStore } from "../store/store";
import type { ScenePrimitive } from "../api/types";
import { DraggableInstance } from "./DraggableInstance";
import { GhostMesh } from "./GhostMesh";
import { GRID_MM, snapToGrid } from "./snap";
import { intersectGroundPlane } from "./dragMath";
import { suggestInstanceName } from "./instanceName";
import { registerTestHooks } from "../testHooks";

const BACKGROUND = "#f2f2f2";

interface ThreeHandle {
  camera: THREE.Camera;
  gl: THREE.WebGLRenderer;
}

function ThreeBridge({ handleRef }: { handleRef: React.MutableRefObject<ThreeHandle | null> }) {
  const three = useThree();
  handleRef.current = { camera: three.camera, gl: three.gl };
  return null;
}

function computeBounds(positions: [number, number, number][]) {
  const box = new THREE.Box3();
  for (const p of positions) box.expandByPoint(new THREE.Vector3(...p));
  const empty = box.isEmpty();
  const center = empty ? new THREE.Vector3(0, 0, 0) : box.getCenter(new THREE.Vector3());
  const extent = empty ? 1 : Math.max(box.getSize(new THREE.Vector3()).length(), 0.3);
  return { center, extent };
}

export function SceneCanvas() {
  const scene = useComposerStore((s) => s.scene);
  const rawCellModules = useComposerStore((s) => s.rawCellModules);
  const hiddenInstances = useComposerStore((s) => s.hiddenInstances);
  const selectedInstance = useComposerStore((s) => s.selectedInstance);
  const toolSlotIncumbent = useComposerStore((s) => s.toolSlotIncumbent);
  const ghost = useComposerStore((s) => s.ghost);
  const selectInstance = useComposerStore((s) => s.selectInstance);
  const placeNewInstance = useComposerStore((s) => s.placeNewInstance);

  const threeRef = useRef<ThreeHandle | null>(null);
  const suppressNextClickRef = useRef(false);
  const controlsRef = useRef<ComponentRef<typeof OrbitControls>>(null);

  // Instance drags must own the pointer exclusively. drei's OrbitControls
  // attaches its own native listeners directly on the canvas element,
  // entirely outside R3F's synthetic event system -- a DraggableInstance's
  // e.stopPropagation() can't reach it. Toggling `enabled` here is the
  // only thing that actually stops the camera from orbiting/panning at
  // the same time as a drag (which is what made drags feel "jumpy": the
  // ray a drag resolves against is computed from the CURRENT camera each
  // event, so a camera that's also moving invalidates the drag's own
  // start reference frame).
  const setControlsEnabled = useCallback((enabled: boolean) => {
    if (controlsRef.current) controlsRef.current.enabled = enabled;
  }, []);

  const worldToScreen = useCallback((xM: number, yM: number, zM: number) => {
    const three = threeRef.current;
    if (!three) return null;
    const ndc = new THREE.Vector3(xM, yM, zM).project(three.camera);
    const rect = three.gl.domElement.getBoundingClientRect();
    return { x: rect.left + ((ndc.x + 1) / 2) * rect.width, y: rect.top + ((1 - ndc.y) / 2) * rect.height };
  }, []);

  // e2e-test-only: WebGL canvas content has no per-object DOM elements a
  // Playwright locator can click, so tests need a way to ask "where on
  // screen is instance X right now" (or an arbitrary mm point) to drive a
  // pointer drag at the right pixel, and "what mm pose did instance X end
  // up at" to assert the result. These read the CURRENT camera + CURRENT
  // store state on every call (not a stale snapshot), so they stay
  // correct as the camera orbits or an instance moves. A no-op in any
  // context nothing calls it from.
  useEffect(() => {
    return registerTestHooks({
      getInstanceScreenXY: (instance: string) => {
        const currentScene = useComposerStore.getState().scene;
        const primitive = currentScene?.primitives.find((p) => p.instance === instance);
        if (!primitive) return null;
        return worldToScreen(...primitive.position);
      },
      worldToScreenXY: (xMm: number, yMm: number, zMm: number) => worldToScreen(xMm / 1000, yMm / 1000, zMm / 1000),
      getInstancePoseMm: (instance: string) => {
        const mount = useComposerStore.getState().rawCellModules.find((m) => m.instance === instance)?.mount;
        return mount?.pose ? mount.pose.xyz_mm : null;
      },
    });
  }, [worldToScreen]);

  const { center, extent } = useMemo(() => {
    if (!scene) return { center: new THREE.Vector3(0, 0, 0), extent: 1 };
    const positions = scene.primitives.map((p) => p.position).concat(scene.markers.map((m) => m.position));
    return computeBounds(positions);
  }, [scene]);

  const mountByInstance = useMemo(() => {
    const map = new Map<string, (typeof rawCellModules)[number]>();
    for (const m of rawCellModules) map.set(m.instance, m);
    return map;
  }, [rawCellModules]);

  const primitivesByInstance = useMemo(() => {
    const map = new Map<string, ScenePrimitive[]>();
    if (!scene) return map;
    for (const p of scene.primitives) {
      if (!map.has(p.instance)) map.set(p.instance, []);
      map.get(p.instance)!.push(p);
    }
    return map;
  }, [scene]);

  const handleDragOver = useCallback((e: React.DragEvent<HTMLDivElement>) => {
    if (e.dataTransfer.types.includes("application/x-ocm-module")) e.preventDefault();
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      const raw = e.dataTransfer.getData("application/x-ocm-module");
      if (!raw || !threeRef.current || !scene) return;
      const { id, revision } = JSON.parse(raw) as { id: string; revision: string };

      const { camera, gl } = threeRef.current;
      const rect = gl.domElement.getBoundingClientRect();
      const ndc = new THREE.Vector2(((e.clientX - rect.left) / rect.width) * 2 - 1, -((e.clientY - rect.top) / rect.height) * 2 + 1);
      const raycaster = new THREE.Raycaster();
      raycaster.setFromCamera(ndc, camera);
      // Same fixed-plane intersection DraggableInstance uses for existing
      // instances (dragMath.ts) -- a new instance always lands at deck
      // height (z=0), never raycast against scene meshes.
      const point = intersectGroundPlane(raycaster.ray, 0);
      if (!point) return;

      let xMm = point.x * 1000;
      let yMm = point.y * 1000;
      if (!e.shiftKey) {
        xMm = snapToGrid(xMm, GRID_MM);
        yMm = snapToGrid(yMm, GRID_MM);
      }

      const instanceName = suggestInstanceName(id, scene.instances);
      void placeNewInstance(id, revision, instanceName, { pose: { xyz_mm: [xMm, yMm, 0], rpy_deg: [0, 0, 0] } });
    },
    [placeNewInstance, scene],
  );

  return (
    <div className="scene-canvas" onDragOver={handleDragOver} onDrop={handleDrop}>
      <Canvas
        camera={{ up: [0, 0, 1], position: [center.x + extent, center.y - extent, center.z + extent * 0.8], fov: 50, near: 0.01, far: 100 }}
        onPointerMissed={() => void selectInstance(null)}
      >
        <ThreeBridge handleRef={threeRef} />
        <color attach="background" args={[BACKGROUND]} />
        <ambientLight intensity={0.6} />
        <directionalLight position={[2, -3, 4]} intensity={0.8} />
        <directionalLight position={[-2, 2, 2]} intensity={0.3} />

        <gridHelper args={[Math.max(extent * 3, 2), 40, 0x999999, 0xdddddd]} rotation={[Math.PI / 2, 0, 0]} />
        <axesHelper args={[Math.max(extent * 0.3, 0.2)]} />

        {scene &&
          // scene.instances (also the sidebar's editable list) deliberately
          // excludes "base" -- it's not a placed/deletable instance. Render
          // targets come from scene.colors' own keys instead, which
          // scene_to_payload always seeds with "base" first precisely so a
          // renderer doesn't have to special-case it back in.
          Object.keys(scene.colors)
            .filter((instance) => !hiddenInstances.has(instance))
            .map((instance) => {
              const primitives = primitivesByInstance.get(instance) ?? [];
              const highlight = instance === toolSlotIncumbent ? "incumbent" : instance === selectedInstance ? "selected" : "none";
              return (
                <DraggableInstance
                  key={instance}
                  instance={instance}
                  primitives={primitives}
                  color={scene.colors[instance] ?? "#888888"}
                  highlight={highlight}
                  mountEntry={mountByInstance.get(instance)}
                  onSelect={(name) => void selectInstance(name)}
                  onDragActiveChange={(active) => setControlsEnabled(!active)}
                  suppressNextClickRef={suppressNextClickRef}
                />
              );
            })}

        {ghost && <GhostMesh ghost={ghost} />}

        <OrbitControls ref={controlsRef} makeDefault target={[center.x, center.y, center.z]} />
      </Canvas>
    </div>
  );
}
