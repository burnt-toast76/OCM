// SPDX-License-Identifier: AGPL-3.0-or-later
// A refused placement's attempted pose, rendered as a translucent red
// ghost -- the visual half of "render refusals, never paraphrase them"
// (the toast carries the engine's own words; this carries WHERE). A
// fixed, generic box: the actual module's real footprint isn't known
// client-side at ghost time (only its id/mount attempt is), and isn't
// the point -- this marks a LOCATION, not a precise silhouette.

import * as THREE from "three";
import type { Ghost } from "../store/store";

const GHOST_SIZE_M: [number, number, number] = [0.15, 0.15, 0.1];

export function GhostMesh({ ghost }: { ghost: Ghost }) {
  const rpyRad = ghost.rpyDeg.map((d) => THREE.MathUtils.degToRad(d)) as [number, number, number];
  const quaternion = new THREE.Quaternion().setFromEuler(new THREE.Euler(rpyRad[0], rpyRad[1], rpyRad[2]));

  return (
    <group position={[ghost.position[0], ghost.position[1], ghost.position[2] + GHOST_SIZE_M[2] / 2]} quaternion={quaternion}>
      <mesh>
        <boxGeometry args={GHOST_SIZE_M} />
        <meshStandardMaterial color="#ff3b30" transparent opacity={0.4} depthWrite={false} />
      </mesh>
      <lineSegments>
        <edgesGeometry args={[new THREE.BoxGeometry(...GHOST_SIZE_M)]} />
        <lineBasicMaterial color="#ff3b30" />
      </lineSegments>
    </group>
  );
}
