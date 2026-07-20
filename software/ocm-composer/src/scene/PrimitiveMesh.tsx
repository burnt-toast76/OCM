// SPDX-License-Identifier: AGPL-3.0-or-later
// Renders one collision primitive with the SAME material rules as
// ocm-generator's own debug HTML viewer (ocm_generator/scene/viewer.py's
// embedded three.js template) -- glassy/translucent base geometry (walls
// nearly invisible so they read as an enclosure, not a wall blocking the
// view; the deck stays more visible as a ground-plane reference),
// translucent placeholders for mesh-only links, opaque for everything
// else. Two renderers drawing the same Scene should look like the same
// cell, not a reinterpretation.

import { useMemo } from "react";
import * as THREE from "three";
import type { ScenePrimitive } from "../api/types";

function makeGeometry(p: ScenePrimitive): THREE.BufferGeometry {
  if (p.kind === "box") {
    return new THREE.BoxGeometry(p.dims.x, p.dims.y, p.dims.z);
  }
  if (p.kind === "cylinder") {
    const g = new THREE.CylinderGeometry(p.dims.radius, p.dims.radius, p.dims.length, 24);
    g.rotateX(Math.PI / 2); // URDF cylinders run along local Z; three.js's run along local Y.
    return g;
  }
  return new THREE.SphereGeometry(p.dims.radius, 16, 12);
}

export type Highlight = "none" | "selected" | "incumbent";

export interface PrimitiveMeshProps {
  primitive: ScenePrimitive;
  color: string;
  highlight?: Highlight;
  onClick?: (instance: string) => void;
}

export function PrimitiveMesh({ primitive: p, color, highlight = "none", onClick }: PrimitiveMeshProps) {
  const geometry = useMemo(() => makeGeometry(p), [p]);

  const isBase = p.instance_kind === "base";
  const isWall = isBase && p.kind === "box" && p.dims.z > 1.0;
  let opacity = 1.0;
  if (p.placeholder) opacity = 0.35;
  else if (isWall) opacity = 0.12;
  else if (isBase) opacity = 0.55;

  const emissive = highlight === "incumbent" ? "#ff3b30" : highlight === "selected" ? "#2f6feb" : "#000000";
  const emissiveIntensity = highlight === "none" ? 0 : 0.45;

  return (
    <mesh
      geometry={geometry}
      position={p.position}
      quaternion={p.quaternion}
      onClick={
        onClick
          ? (e) => {
              e.stopPropagation();
              onClick(p.instance);
            }
          : undefined
      }
    >
      <meshStandardMaterial
        color={color}
        transparent={p.placeholder || isBase}
        opacity={opacity}
        depthWrite={!isWall}
        side={isWall ? THREE.DoubleSide : THREE.FrontSide}
        roughness={0.6}
        metalness={0.05}
        emissive={emissive}
        emissiveIntensity={emissiveIntensity}
      />
    </mesh>
  );
}
