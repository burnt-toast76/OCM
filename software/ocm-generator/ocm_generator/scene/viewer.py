# SPDX-License-Identifier: AGPL-3.0-or-later
"""Render a composed Scene as a single self-contained HTML file: three.js
loaded from a CDN via an import map, no build step, no npm, no server --
open it by double-clicking. A debug tool for eyeballing what build_scene()
actually assembled, not the product viewer (see ADR-0007's note on
ocm-viewer's own R3F + GLB pipeline -- a different, much bigger tool this
doesn't touch).

Geometry (every collision primitive a link carries, not just its first --
see .kinematics) is walked directly out of the composed URDF
(Scene.urdf_xml), through the same joint-state-aware forward kinematics
the workspace containment check uses (.kinematics.compute_world_poses),
so a cell.yaml joint_state is reflected in what gets drawn. Anything left
unspecified -- and every fixed joint -- sits at zero: a static snapshot,
not a live simulator. Links whose only <collision><geometry> is a <mesh>
(currently just the vendored UR5e) get a small translucent placeholder
marker instead of their real shape -- adding an STL/mesh loader is
explicitly out of scope for this tool; box/cylinder/sphere primitives are
simple enough to serialize as plain JSON and hand to three.js directly.
"""

from __future__ import annotations

import html
import json
import math
import xml.etree.ElementTree as ET
from typing import Any

from ocm_resolve import ResolvedCell

from .build import WORLD_LINK, Scene
from .kinematics import compute_world_poses, list_collision_primitives
from .transforms import Pose

_PALETTE = [
    "#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4",
    "#46f0f0", "#f032e6", "#bcf60c", "#fabebe", "#008080",
    "#e6beff", "#9a6324", "#808000", "#000075",
]


def _mm_to_m(xyz_mm: tuple[float, float, float]) -> tuple[float, float, float]:
    return (xyz_mm[0] / 1000.0, xyz_mm[1] / 1000.0, xyz_mm[2] / 1000.0)


def _deg_to_rad(rpy_deg: tuple[float, float, float]) -> tuple[float, float, float]:
    return (math.radians(rpy_deg[0]), math.radians(rpy_deg[1]), math.radians(rpy_deg[2]))


def _instance_of(link_name: str, scene: Scene) -> str:
    if link_name in scene.base.link_names:
        return "base"
    for name, inst in scene.instances.items():
        if link_name in inst.link_names:
            return name
    return "?"


def _markers(scene: Scene, resolved: ResolvedCell, world_poses: dict[str, Pose]) -> list[dict[str, Any]]:
    """Points worth calling out: where each mount.on chain actually attaches
    (e.g. sd1 onto robot1's real flange link), and any instance's declared
    TCP frame (a manifest-level concept -- frames.tcp -- with no URDF link
    of its own, so it has to be computed here rather than walked out of
    the URDF like everything else).
    """
    markers: list[dict[str, Any]] = []

    for name, inst in scene.instances.items():
        if inst.parent_link == WORLD_LINK:
            continue
        pose = world_poses.get(inst.parent_link)
        if pose is not None:
            markers.append({"label": f"{inst.parent_link} (mount for {name})", "position": list(pose.translation)})

    for name, ri in resolved.instances.items():
        tcp = ri.module.mechanical.frames.get("tcp")
        if tcp is None:
            continue
        origin_pose = world_poses.get(f"{name}__origin")
        if origin_pose is None:
            continue
        tcp_local = Pose.from_xyz_rpy(_mm_to_m(tuple(tcp.xyz_mm)), _deg_to_rad(tuple(tcp.rpy_deg)))
        world = origin_pose.compose(tcp_local)
        markers.append({"label": f"{name} TCP", "position": list(world.translation)})

    return markers


def scene_to_payload(scene: Scene, resolved: ResolvedCell) -> dict[str, Any]:
    """Everything the HTML/JS side needs, as plain JSON-able data: one
    entry per collision primitive (a link may carry several -- see
    .kinematics), a color per instance, and attachment/TCP markers.
    """
    root = ET.fromstring(scene.urdf_xml)
    world_poses = compute_world_poses(root, scene.joint_state, WORLD_LINK)

    instance_names = ["base"] + sorted(scene.instances)
    colors = {name: _PALETTE[i % len(_PALETTE)] for i, name in enumerate(instance_names)}

    primitives: list[dict[str, Any]] = []
    for link in root.findall("link"):
        name = link.get("name")
        if not name or name == WORLD_LINK or name not in world_poses:
            continue
        for prim in list_collision_primitives(link, world_poses[name]):
            primitives.append(
                {
                    "link": name,
                    "instance": _instance_of(name, scene),
                    "kind": prim.kind,
                    "dims": prim.dims,
                    "position": list(prim.world.translation),
                    "quaternion": list(prim.world.quaternion_xyzw()),
                    "placeholder": prim.placeholder,
                }
            )

    return {
        "cell_id": resolved.cell.id,
        "instances": instance_names,
        "colors": colors,
        "primitives": primitives,
        "markers": _markers(scene, resolved, world_poses),
    }


_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>OCM scene: __CELL_ID__</title>
<style>
  html, body { margin: 0; height: 100%; overflow: hidden; background: #f2f2f2; font-family: system-ui, -apple-system, sans-serif; }
  #legend {
    position: absolute; top: 10px; left: 10px; z-index: 10;
    background: rgba(255,255,255,0.92); border: 1px solid #ccc; border-radius: 6px;
    padding: 10px 14px; font-size: 13px; line-height: 1.7; box-shadow: 0 1px 4px rgba(0,0,0,0.15);
    max-width: 260px;
  }
  #legend h1 { font-size: 13px; margin: 0 0 6px 0; font-weight: 600; word-break: break-all; }
  #legend .row { display: flex; align-items: center; gap: 6px; }
  .swatch { display: inline-block; width: 12px; height: 12px; border-radius: 3px; flex: none; }
  #hint { position: absolute; bottom: 8px; left: 10px; z-index: 10; font-size: 11px; color: #666; }
  .obj-label {
    color: #111; background: rgba(255,255,255,0.85); padding: 1px 5px; border-radius: 3px;
    font-size: 11px; white-space: nowrap; border: 1px solid rgba(0,0,0,0.15);
  }
</style>
</head>
<body>
<div id="legend">
  <h1>__CELL_ID__</h1>
  __LEGEND_ROWS__
</div>
<div id="hint">drag to orbit &middot; scroll to zoom &middot; right-drag to pan</div>

<script type="importmap">
{
  "imports": {
    "three": "https://unpkg.com/three@0.160.0/build/three.module.js",
    "three/addons/": "https://unpkg.com/three@0.160.0/examples/jsm/"
  }
}
</script>
<script type="module">
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { CSS2DRenderer, CSS2DObject } from "three/addons/renderers/CSS2DRenderer.js";

const DATA = __DATA_JSON__;

const scene = new THREE.Scene();
scene.background = new THREE.Color(0xf2f2f2);

const camera = new THREE.PerspectiveCamera(50, window.innerWidth / window.innerHeight, 0.01, 100);
camera.up.set(0, 0, 1); // URDF/world convention is Z-up; three.js defaults to Y-up.

const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.setPixelRatio(window.devicePixelRatio);
document.body.appendChild(renderer.domElement);

const labelRenderer = new CSS2DRenderer();
labelRenderer.setSize(window.innerWidth, window.innerHeight);
labelRenderer.domElement.style.position = "absolute";
labelRenderer.domElement.style.top = "0px";
labelRenderer.domElement.style.pointerEvents = "none"; // clicks/drags pass through to the WebGL canvas underneath
document.body.appendChild(labelRenderer.domElement);

scene.add(new THREE.AmbientLight(0xffffff, 0.6));
const sun = new THREE.DirectionalLight(0xffffff, 0.8);
sun.position.set(2, -3, 4);
scene.add(sun);
const fill = new THREE.DirectionalLight(0xffffff, 0.3);
fill.position.set(-2, 2, 2);
scene.add(fill);

// Compute a content bounding box from raw data BEFORE building any mesh,
// so the grid/camera/controls can be sized to whatever cell this is --
// not hardcoded to bracket-asm-01's dimensions.
const bounds = new THREE.Box3();
for (const p of DATA.primitives) bounds.expandByPoint(new THREE.Vector3(p.position[0], p.position[1], p.position[2]));
for (const m of DATA.markers) bounds.expandByPoint(new THREE.Vector3(m.position[0], m.position[1], m.position[2]));
const center = bounds.isEmpty() ? new THREE.Vector3(0, 0, 0) : bounds.getCenter(new THREE.Vector3());
const extent = bounds.isEmpty() ? 1 : Math.max(bounds.getSize(new THREE.Vector3()).length(), 0.3);

// Ground grid at z=0. GridHelper's native plane is XZ (y=0); rotate it
// onto the XY plane (z=0) to match URDF/world convention.
const grid = new THREE.GridHelper(Math.max(extent * 3, 2), 40, 0x999999, 0xdddddd);
grid.rotation.x = Math.PI / 2;
scene.add(grid);

scene.add(new THREE.AxesHelper(Math.max(extent * 0.3, 0.2)));

function makeGeometry(p) {
  if (p.kind === "box") {
    return new THREE.BoxGeometry(p.dims.x, p.dims.y, p.dims.z);
  }
  if (p.kind === "cylinder") {
    // URDF cylinders run along their local Z axis; three.js's run along
    // local Y -- bake in the remap once, on the geometry itself.
    const g = new THREE.CylinderGeometry(p.dims.radius, p.dims.radius, p.dims.length, 24);
    g.rotateX(Math.PI / 2);
    return g;
  }
  return new THREE.SphereGeometry(p.dims.radius, 16, 12);
}

const group = new THREE.Group();
scene.add(group);

for (const p of DATA.primitives) {
  const material = new THREE.MeshStandardMaterial({
    color: new THREE.Color(DATA.colors[p.instance] || "#888888"),
    transparent: p.placeholder,
    opacity: p.placeholder ? 0.35 : 1.0,
    roughness: 0.6,
    metalness: 0.05,
  });
  const mesh = new THREE.Mesh(makeGeometry(p), material);
  mesh.position.set(p.position[0], p.position[1], p.position[2]);
  mesh.quaternion.set(p.quaternion[0], p.quaternion[1], p.quaternion[2], p.quaternion[3]);
  group.add(mesh);
}

function addLabel(text, position) {
  const div = document.createElement("div");
  div.className = "obj-label";
  div.textContent = text;
  const obj = new CSS2DObject(div);
  obj.position.set(position[0], position[1], position[2]);
  group.add(obj);
}

for (const m of DATA.markers) {
  const marker = new THREE.Mesh(
    new THREE.SphereGeometry(Math.max(extent * 0.01, 0.008), 12, 8),
    new THREE.MeshBasicMaterial({ color: 0x222222 })
  );
  marker.position.set(m.position[0], m.position[1], m.position[2]);
  group.add(marker);
  addLabel(m.label, m.position);
}

camera.position.set(center.x + extent, center.y - extent, center.z + extent * 0.8);

const controls = new OrbitControls(camera, renderer.domElement);
controls.target.copy(center);
controls.update();

window.addEventListener("resize", () => {
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
  labelRenderer.setSize(window.innerWidth, window.innerHeight);
});

function animate() {
  requestAnimationFrame(animate);
  controls.update();
  renderer.render(scene, camera);
  labelRenderer.render(scene, camera);
}
animate();
</script>
</body>
</html>
"""


def render_html(scene: Scene, resolved: ResolvedCell) -> str:
    """Render a Scene into a single self-contained HTML file: three.js from
    a CDN via an import map, the composed geometry embedded as JSON. Open
    it by double-clicking -- no server, no build step.
    """
    payload = scene_to_payload(scene, resolved)
    cell_id = html.escape(payload["cell_id"])
    data_json = json.dumps(payload).replace("</", "<\\/")  # don't let the JSON prematurely close </script>

    legend_rows = "\n  ".join(
        f'<div class="row"><span class="swatch" style="background:{payload["colors"][name]}"></span>{html.escape(name)}</div>'
        for name in payload["instances"]
    )

    page = _TEMPLATE.replace("__CELL_ID__", cell_id)
    page = page.replace("__DATA_JSON__", data_json)
    page = page.replace("__LEGEND_ROWS__", legend_rows)
    return page
