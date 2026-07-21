// SPDX-License-Identifier: AGPL-3.0-or-later
// A small R3F preview of a component's converted GLB (spec/09: "If a GLB
// exists in the component dir, render it"). Orbit-only, no drag/edit --
// this is a geometry sanity check, not the cell composer. <Bounds> auto-
// fits the camera to whatever loads, sidestepping any assumption about
// the GLB's native units (cascadio's STEP conversion keeps the source
// file's own scale, which isn't guaranteed to be meters).

import { Suspense } from "react";
import { Canvas } from "@react-three/fiber";
import { Bounds, OrbitControls, useGLTF } from "@react-three/drei";

function GlbModel({ url }: { url: string }) {
  const { scene } = useGLTF(url);
  return <primitive object={scene} />;
}

export function GlbViewer({ url }: { url: string }) {
  return (
    <div className="glb-viewer">
      <Canvas camera={{ position: [1, -1, 1], fov: 45 }}>
        <color attach="background" args={["#f2f2f2"]} />
        <ambientLight intensity={0.7} />
        <directionalLight position={[2, -3, 4]} intensity={0.8} />
        <Suspense fallback={null}>
          <Bounds fit clip observe margin={1.3}>
            <GlbModel url={url} />
          </Bounds>
        </Suspense>
        <OrbitControls makeDefault />
      </Canvas>
    </div>
  );
}
