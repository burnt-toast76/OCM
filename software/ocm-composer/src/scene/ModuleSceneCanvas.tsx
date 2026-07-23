// SPDX-License-Identifier: AGPL-3.0-or-later
// The Modules page's own 3D view -- deliberately NOT SceneCanvas.tsx
// (that one is wired to build_scene's server-computed primitives/mount.on/
// cell-specific refusal-ghost logic, none of which applies here). Renders
// the module's own uploaded STEP file as a non-interactive visual backdrop
// (no pointer handlers at all -- never sliced, never clicked, cascadio
// doesn't expose per-part structure). Camera/lighting/grid setup copied
// wholesale from SceneCanvas.tsx (none of that is cell-specific).
//
// Also renders one draggable ComponentInstance per posed components[] row.

import { Suspense, useMemo, useRef } from "react";
import type { ComponentRef } from "react";
import { Canvas } from "@react-three/fiber";
import { Bounds, OrbitControls, useGLTF } from "@react-three/drei";
import { moduleAttachmentDownloadUrl } from "../api/client";
import { useModulesStore } from "../store/modulesStore";
import { ComponentInstance } from "./ComponentInstance";

const BACKGROUND = "#f2f2f2";
const GRID_EXTENT_M = 2;

// No pointer handlers anywhere on this component or its <primitive> --
// that absence is the entire point (regression-check by hand: clicking or
// dragging the backdrop must never select or move anything).
function BackdropModel({ url }: { url: string }) {
  const { scene } = useGLTF(url);
  return <primitive object={scene} />;
}

export function ModuleSceneCanvas() {
  const selectedModuleId = useModulesStore((s) => s.selectedModuleId);
  const attachments = useModulesStore((s) => s.attachments);
  const detail = useModulesStore((s) => s.detail);
  const componentGlbUrls = useModulesStore((s) => s.componentGlbUrls);
  const dragging = useModulesStore((s) => s.dragging);
  const selectComponentInstance = useModulesStore((s) => s.selectComponentInstance);

  const controlsRef = useRef<ComponentRef<typeof OrbitControls>>(null);
  const suppressNextClickRef = useRef(false);

  // Decisions locked in (approved plan): no backdrop-GLB selector -- just
  // whichever STEP-derived attachment is glb_status: "ready", most
  // recently uploaded. One STEP backdrop per module is the expected case.
  const backdropUrl = useMemo(() => {
    if (!selectedModuleId) return null;
    const ready = attachments.filter((a) => a.kind === "step" && a.glb_status === "ready" && a.glb);
    const last = ready[ready.length - 1];
    return last?.glb ? moduleAttachmentDownloadUrl(selectedModuleId, last.glb) : null;
  }, [attachments, selectedModuleId]);

  const components = detail?.manifest.components ?? [];

  return (
    <div className="module-scene-canvas">
      <Canvas
        camera={{ up: [0, 0, 1], position: [0.5, -0.5, 0.4], fov: 50, near: 0.01, far: 100 }}
        onPointerMissed={() => selectComponentInstance(null)}
      >
        <color attach="background" args={[BACKGROUND]} />
        <ambientLight intensity={0.6} />
        <directionalLight position={[2, -3, 4]} intensity={0.8} />
        <directionalLight position={[-2, 2, 2]} intensity={0.3} />

        <gridHelper args={[GRID_EXTENT_M, 40, 0x999999, 0xdddddd]} rotation={[Math.PI / 2, 0, 0]} />
        <axesHelper args={[0.2]} />

        {backdropUrl && (
          <Suspense fallback={null}>
            <Bounds fit clip observe margin={1.3}>
              <BackdropModel url={backdropUrl} />
            </Bounds>
          </Suspense>
        )}

        {components.map(
          (c) =>
            c.pose && (
              <Suspense key={c.refdes} fallback={null}>
                <ComponentInstance component={c} pose={c.pose} glbUrl={componentGlbUrls[c.ref.split("@")[0]] ?? null} suppressNextClickRef={suppressNextClickRef} />
              </Suspense>
            ),
        )}

        <OrbitControls ref={controlsRef} makeDefault enabled={!dragging} />
      </Canvas>
    </div>
  );
}
