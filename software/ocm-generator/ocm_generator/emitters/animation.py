# SPDX-License-Identifier: AGPL-3.0-or-later
"""Embed a planned FasteningPlan's motion into the same self-contained
HTML viewer `ocm_generator.scene.viewer` builds statically, and animate it
-- `ocm plan --view-animation`.

## Reuse the collision-check states -- never recompute or re-derive motion

Every animation frame is a joint-angle state `ocm_generator.planner.path.
check_joint_segment` already interpolated and ran through a real discrete
collision check for THIS plan (`PathSegment.frames` -- see that module's
own docstring). This module never re-interpolates a path of its own; it
only runs each ALREADY-CHECKED state through the same forward kinematics
(`.scene.kinematics.compute_world_poses`) the static viewer and the
workspace containment check use, to get link poses to draw. An animation
frame is therefore always a state that has already been proven
collision-free -- not a separately-interpolated, unchecked one.

## Segments and dwells

`DATA.animation` is a flat, ordered list matching `ocm_generator.planner.
cycle_time.CycleTimeReport.rows` one-for-one -- literally the same rows
the printed cycle-time table shows, so a segment's caption and duration in
the viewer are the exact numbers in that table, not a separately-computed
estimate. By `CycleTimeRow.kind` (ADR-0029 D3):

- **motion** rows carry every frame from the matching `PathSegment.frames`
  -- real per-frame motion, reused wholesale.
- **dwell** and **actuation** rows carry exactly ONE held frame, looked up
  via `CycleTimeRow.held_at_segment` (the matching PathSegment's own LAST
  frame -- e.g. drive_screw's held pose is the approach segment's last
  frame, i.e. contact), or the scene's own initial state for a row that
  precedes all motion (e.g. the opening clamp). The pause is real and
  visible: this is where spec/08's handshake actually lives -- see
  spec/08-robot-handshake.md. An actuation row is held rather than swept
  ON PURPOSE in phase 1: D6 requires every emitted frame to have been
  collision-checked, and the checker for actuation sweeps is phase 2 --
  emitting unchecked interpolated frames would put unverified motion on
  screen looking identical to verified motion, the exact failure D6
  exists to prevent. So the jaws do not move yet; the timeline pauses
  where the plan says the actuation happens.

No smoothing, no retiming: playback is linear between whatever frames were
actually checked, at a constant per-frame timestep within each motion
segment (`duration_s / (len(frames) - 1)`). Honest v0 -- jerk-limited
timing arrives with Ruckig later (ADR-0007).

## Dynamic vs static geometry

"The robot and everything mounted on it" (transitively -- sd1 rides
robot1's flange) gets a NEW world pose every frame; everything else
(base, feed1, nest1, cam1, ...) is emitted once, exactly as the plain
`--view` output already does (`.scene.viewer.scene_to_payload`, reused
directly and filtered) -- a static module's mesh is built once in JS and
never touched again during playback.

## Vendored three.js -- no CDN

Unlike the plain `--view` debug viewer (unchanged, still loads three.js
from a CDN via an import map), this output is meant to be genuinely
self-contained: openable with no network access at all. The three files
`.scene.vendor.three` carries (three.js core + the OrbitControls and
CSS2DRenderer addons, MIT-licensed -- see that directory's own NOTICE.md)
are embedded as `data:` URIs directly in the generated page's own `<script
type="importmap">`. No blob URLs, no runtime fetch, no build step.
"""

from __future__ import annotations

import base64
import html
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from ocm_resolve import ResolvedCell

from ocm_generator.errors import OcmGeneratorError
from ocm_generator.planner import CycleTimeReport, FasteningPlan
from ocm_generator.scene.build import WORLD_LINK, Scene
from ocm_generator.scene.kinematics import compute_world_poses, list_collision_primitives
from ocm_generator.scene.transforms import Pose
from ocm_generator.scene.viewer import _instance_kinds, _instance_of, scene_to_payload

_VENDOR_DIR = Path(__file__).resolve().parent.parent / "scene" / "vendor" / "three"


class AnimationError(OcmGeneratorError):
    """The cycle-time report and the plan's own segments disagree about
    what exists -- an internal-consistency bug (both are built from the
    same FasteningPlan in the same call), not a user-facing refusal.
    """


def _dynamic_instances(scene: Scene, robot_instance: str) -> set[str]:
    """`robot_instance` plus every instance mounted on it, transitively
    (sd1 on robot1's flange; a future tool mounted ON sd1 would count too)
    -- everything that needs a fresh world pose per animation frame.
    """
    dynamic = {robot_instance}
    changed = True
    while changed:
        changed = False
        for name, inst in scene.instances.items():
            if name in dynamic:
                continue
            parent_instance = "base" if inst.parent_link == WORLD_LINK else _instance_of(inst.parent_link, scene)
            if parent_instance in dynamic:
                dynamic.add(name)
                changed = True
    return dynamic


def _dynamic_link_names(scene: Scene, dynamic_instances: set[str]) -> set[str]:
    names: set[str] = set()
    for name in dynamic_instances:
        names |= scene.base.link_names if name == "base" else scene.instance(name).link_names
    return names


def _dynamic_primitive_specs(root: ET.Element, dynamic_link_names: set[str], scene: Scene, resolved: ResolvedCell) -> list[dict[str, Any]]:
    """Static metadata only (kind/dims/instance/instance_kind/link/
    placeholder) for every dynamic-instance collision primitive, in URDF
    document order -- that order is authoritative: every animation frame's
    per-primitive transform list (`_frame_transforms`) is built by the
    exact same walk, so the two stay index-aligned by construction.
    """
    instance_kinds = _instance_kinds(resolved)
    specs: list[dict[str, Any]] = []
    for link in root.findall("link"):
        name = link.get("name")
        if not name or name not in dynamic_link_names:
            continue
        instance = _instance_of(name, scene)
        for prim in list_collision_primitives(link, Pose.identity()):
            specs.append(
                {
                    "link": name,
                    "instance": instance,
                    "instance_kind": instance_kinds.get(instance, "?"),
                    "kind": prim.kind,
                    "dims": prim.dims,
                    "placeholder": prim.placeholder,
                }
            )
    return specs


def _frame_transforms(root: ET.Element, frame: dict[str, float], dynamic_link_names: set[str]) -> list[dict[str, Any]]:
    """Every dynamic primitive's {position, quaternion} for one already-
    checked frame -- which IS a full namespaced joint-state dict (ADR-0029
    D2), fed straight to forward kinematics. The same document-order walk
    `_dynamic_primitive_specs` used, so index `i` here is index `i` there.
    """
    world_poses = compute_world_poses(root, frame, WORLD_LINK)

    transforms: list[dict[str, Any]] = []
    for link in root.findall("link"):
        name = link.get("name")
        if not name or name not in dynamic_link_names or name not in world_poses:
            continue
        for prim in list_collision_primitives(link, world_poses[name]):
            transforms.append({"position": list(prim.world.translation), "quaternion": list(prim.world.quaternion_xyzw())})
    return transforms


def build_animation_payload(scene: Scene, resolved: ResolvedCell, plan: FasteningPlan, cycle_report: CycleTimeReport) -> dict[str, Any]:
    """Everything the animated viewer needs beyond the plain `scene_to_
    payload` output: dynamic-primitive metadata (built once) and the
    ordered `animation` segment list (one entry per `cycle_report.rows`
    row), each carrying real per-frame transforms already proven
    collision-free -- see module docstring.
    """
    root = ET.fromstring(scene.urdf_xml)
    dynamic_instances = _dynamic_instances(scene, plan.robot_instance)
    dynamic_link_names = _dynamic_link_names(scene, dynamic_instances)
    dynamic_primitives = _dynamic_primitive_specs(root, dynamic_link_names, scene, resolved)

    segments_by_label = {segment.label: segment for segment in plan.segments}

    def frames_for(frames: tuple[dict[str, float], ...]) -> list[list[dict[str, Any]]]:
        return [_frame_transforms(root, frame, dynamic_link_names) for frame in frames]

    animation: list[dict[str, Any]] = []
    for row in cycle_report.rows:
        if row.kind == "motion":
            segment = segments_by_label.get(row.label)
            if segment is None or not segment.frames:
                raise AnimationError(f"cycle-time row {row.label!r} has no matching checked PathSegment frames")
            animation.append(
                {
                    "name": row.label,
                    "kind": "motion",
                    "hole_id": segment.hole_id,
                    "duration_s": row.duration_s,
                    "frames": frames_for(segment.frames),
                }
            )
        else:
            # A stationary row (dwell/actuation) holds ONE frame: its
            # held_at_segment's last checked frame, or -- for a row that
            # precedes all motion, like the opening clamp -- the scene's
            # own initial state, which every checked segment departs from.
            if row.held_at_segment is None:
                held_frame: dict[str, float] = scene.joint_state
                hole_id = None
            else:
                held_segment = segments_by_label.get(row.held_at_segment)
                if held_segment is None or not held_segment.frames:
                    raise AnimationError(f"cycle-time row {row.label!r} ({row.kind}) has no held_at_segment frame to show")
                held_frame = held_segment.frames[-1]
                hole_id = held_segment.hole_id
            animation.append(
                {
                    "name": row.label,
                    "kind": row.kind,
                    "hole_id": hole_id,
                    "duration_s": row.duration_s,
                    "frames": frames_for((held_frame,)),
                }
            )

    return {
        "dynamic_primitives": dynamic_primitives,
        "animation": animation,
        "total_duration_s": cycle_report.total_s,
    }


def _vendor_data_uri(filename: str) -> str:
    data = (_VENDOR_DIR / filename).read_bytes()
    return "data:text/javascript;base64," + base64.b64encode(data).decode("ascii")


_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>OCM plan animation: __CELL_ID__</title>
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
  #player {
    position: absolute; left: 50%; bottom: 16px; transform: translateX(-50%); z-index: 10;
    background: rgba(255,255,255,0.95); border: 1px solid #ccc; border-radius: 8px;
    padding: 10px 16px; box-shadow: 0 1px 6px rgba(0,0,0,0.2);
    width: min(640px, 90vw); font-size: 13px;
  }
  #player .controls { display: flex; align-items: center; gap: 10px; }
  #player button { font-size: 13px; padding: 4px 10px; cursor: pointer; }
  #player select { font-size: 13px; }
  #player input[type=range] { flex: 1; }
  #caption { margin-top: 6px; text-align: center; }
  #caption .name { font-weight: 600; }
  #caption .dwell { color: #a15c00; }
  #caption .time { color: #555; margin-left: 8px; }
</style>
</head>
<body>
<div id="legend">
  <h1>__CELL_ID__</h1>
  __LEGEND_ROWS__
</div>
<div id="hint">drag to orbit &middot; scroll to zoom &middot; right-drag to pan</div>

<div id="player">
  <div class="controls">
    <button id="playPause">Play</button>
    <input id="scrub" type="range" min="0" max="1000" value="0" step="1"/>
    <select id="speed">
      <option value="0.5">0.5&times;</option>
      <option value="1" selected>1&times;</option>
      <option value="2">2&times;</option>
    </select>
  </div>
  <div id="caption"><span class="name">--</span><span class="time"></span></div>
</div>

<script type="importmap">
{
  "imports": {
    "three": "__THREE_DATA_URI__",
    "three/addons/controls/OrbitControls.js": "__ORBITCONTROLS_DATA_URI__",
    "three/addons/renderers/CSS2DRenderer.js": "__CSS2DRENDERER_DATA_URI__"
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
labelRenderer.domElement.style.pointerEvents = "none";
document.body.appendChild(labelRenderer.domElement);

scene.add(new THREE.AmbientLight(0xffffff, 0.6));
const sun = new THREE.DirectionalLight(0xffffff, 0.8);
sun.position.set(2, -3, 4);
scene.add(sun);
const fill = new THREE.DirectionalLight(0xffffff, 0.3);
fill.position.set(-2, 2, 2);
scene.add(fill);

const bounds = new THREE.Box3();
for (const p of DATA.primitives) bounds.expandByPoint(new THREE.Vector3(p.position[0], p.position[1], p.position[2]));
for (const m of DATA.markers) bounds.expandByPoint(new THREE.Vector3(m.position[0], m.position[1], m.position[2]));
const center = bounds.isEmpty() ? new THREE.Vector3(0, 0, 0) : bounds.getCenter(new THREE.Vector3());
const extent = bounds.isEmpty() ? 1 : Math.max(bounds.getSize(new THREE.Vector3()).length(), 0.3);

const grid = new THREE.GridHelper(Math.max(extent * 3, 2), 40, 0x999999, 0xdddddd);
grid.rotation.x = Math.PI / 2;
scene.add(grid);
scene.add(new THREE.AxesHelper(Math.max(extent * 0.3, 0.2)));

function makeGeometry(p) {
  if (p.kind === "box") return new THREE.BoxGeometry(p.dims.x, p.dims.y, p.dims.z);
  if (p.kind === "cylinder") {
    const g = new THREE.CylinderGeometry(p.dims.radius, p.dims.radius, p.dims.length, 24);
    g.rotateX(Math.PI / 2);
    return g;
  }
  return new THREE.SphereGeometry(p.dims.radius, 16, 12);
}

function makeMaterial(p) {
  const isBase = p.instance_kind === "base";
  const isWall = isBase && p.kind === "box" && p.dims.z > 1.0;
  let opacity = 1.0;
  if (p.placeholder) opacity = 0.35;
  else if (isWall) opacity = 0.12;
  else if (isBase) opacity = 0.55;
  return new THREE.MeshStandardMaterial({
    color: new THREE.Color(DATA.colors[p.instance] || "#888888"),
    transparent: p.placeholder || isBase,
    opacity,
    depthWrite: !isWall,
    side: isWall ? THREE.DoubleSide : THREE.FrontSide,
    roughness: 0.6,
    metalness: 0.05,
  });
}

const group = new THREE.Group();
scene.add(group);

// Static modules -- built once, never touched again (DATA.primitives here
// already excludes every dynamic instance; see animation.py).
for (const p of DATA.primitives) {
  const mesh = new THREE.Mesh(makeGeometry(p), makeMaterial(p));
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

// Dynamic modules (the robot + everything mounted on it) -- one mesh per
// primitive, built once from DATA.dynamic_primitives; only their
// position/quaternion change, every animation frame.
const dynamicMeshes = DATA.dynamic_primitives.map((p) => {
  const mesh = new THREE.Mesh(makeGeometry(p), makeMaterial(p));
  group.add(mesh);
  return mesh;
});

function applyFrame(frame) {
  for (let i = 0; i < dynamicMeshes.length; i++) {
    const t = frame[i];
    if (!t) continue;
    dynamicMeshes[i].position.set(t.position[0], t.position[1], t.position[2]);
    dynamicMeshes[i].quaternion.set(t.quaternion[0], t.quaternion[1], t.quaternion[2], t.quaternion[3]);
  }
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

// ---------------------------------------------------------------------
// Playback: linear replay of exactly the states already checked -- no
// smoothing, no retiming. Within a motion segment, frame k sits at
// k * (duration_s / (frames.length - 1)); a dwell has exactly one frame
// held for its whole duration_s. Cross-fading between two ADJACENT
// already-checked frames (position lerp, quaternion slerp) is still
// linear playback of the checked states, not an inserted state.
// ---------------------------------------------------------------------

const segments = DATA.animation;
const totalDuration = DATA.total_duration_s;

const playPauseBtn = document.getElementById("playPause");
const scrub = document.getElementById("scrub");
const speedSelect = document.getElementById("speed");
const captionName = document.querySelector("#caption .name");
const captionTime = document.querySelector("#caption .time");

let playing = false;
let elapsed = 0; // seconds, 0..totalDuration
let scrubbing = false;

function fmt(t) {
  return t.toFixed(1) + "s";
}

function locate(t) {
  // (segment index, local time within it) for global elapsed time t.
  let acc = 0;
  for (let i = 0; i < segments.length; i++) {
    const d = segments[i].duration_s;
    if (t <= acc + d || i === segments.length - 1) {
      return [i, Math.max(0, Math.min(d, t - acc))];
    }
    acc += d;
  }
  return [segments.length - 1, 0];
}

function render(t) {
  t = Math.max(0, Math.min(totalDuration, t));
  const [segIndex, localT] = locate(t);
  const seg = segments[segIndex];
  const frames = seg.frames;

  if (frames.length === 1 || seg.duration_s <= 0) {
    applyFrame(frames[0]);
  } else {
    const step = seg.duration_s / (frames.length - 1);
    const raw = localT / step;
    const i0 = Math.max(0, Math.min(frames.length - 1, Math.floor(raw)));
    const i1 = Math.min(frames.length - 1, i0 + 1);
    const frac = raw - i0;
    if (i0 === i1 || frac <= 0) {
      applyFrame(frames[i0]);
    } else {
      const blended = frames[i0].map((a, idx) => {
        const b = frames[i1][idx];
        const pos = [0, 1, 2].map((k) => a.position[k] + (b.position[k] - a.position[k]) * frac);
        const qa = new THREE.Quaternion(...a.quaternion);
        const qb = new THREE.Quaternion(...b.quaternion);
        qa.slerp(qb, frac);
        return { position: pos, quaternion: [qa.x, qa.y, qa.z, qa.w] };
      });
      applyFrame(blended);
    }
  }

  captionName.textContent = seg.kind === "dwell" ? `${seg.name} — waiting on PLC` : seg.name;
  captionName.className = "name" + (seg.kind === "dwell" ? " dwell" : "");
  captionTime.textContent = ` ${fmt(t)} / ${fmt(totalDuration)}`;
  if (!scrubbing) scrub.value = String(Math.round((t / totalDuration) * 1000));
}

render(0);

playPauseBtn.addEventListener("click", () => {
  playing = !playing;
  playPauseBtn.textContent = playing ? "Pause" : "Play";
  if (playing && elapsed >= totalDuration) elapsed = 0;
});

scrub.addEventListener("input", () => {
  scrubbing = true;
  elapsed = (parseFloat(scrub.value) / 1000) * totalDuration;
  render(elapsed);
});
scrub.addEventListener("change", () => { scrubbing = false; });

let lastTick = performance.now();
function tick(now) {
  requestAnimationFrame(tick);
  const dt = (now - lastTick) / 1000;
  lastTick = now;

  if (playing && !scrubbing) {
    const speed = parseFloat(speedSelect.value);
    elapsed += dt * speed;
    if (elapsed >= totalDuration) {
      elapsed = totalDuration;
      playing = false;
      playPauseBtn.textContent = "Play";
    }
    render(elapsed);
  }

  controls.update();
  renderer.render(scene, camera);
  labelRenderer.render(scene, camera);
}
requestAnimationFrame(tick);
</script>
</body>
</html>
"""


def render_html_animation(scene: Scene, resolved: ResolvedCell, plan: FasteningPlan, cycle_report: CycleTimeReport) -> str:
    """Render `scene`'s composed geometry PLUS `plan`'s already-checked
    motion into one self-contained, animated HTML file -- vendored
    three.js, no CDN, no server, no build step. Open by double-clicking.
    """
    static_payload = scene_to_payload(scene, resolved)
    dynamic_instances = _dynamic_instances(scene, plan.robot_instance)
    static_payload["primitives"] = [p for p in static_payload["primitives"] if p["instance"] not in dynamic_instances]

    animation_payload = build_animation_payload(scene, resolved, plan, cycle_report)
    payload = {**static_payload, **animation_payload}

    cell_id = html.escape(payload["cell_id"])
    data_json = json.dumps(payload).replace("</", "<\\/")

    legend_rows = "\n  ".join(
        f'<div class="row"><span class="swatch" style="background:{payload["colors"][name]}"></span>{html.escape(name)}</div>'
        for name in payload["instances"]
    )

    page = _TEMPLATE.replace("__CELL_ID__", cell_id)
    page = page.replace("__DATA_JSON__", data_json)
    page = page.replace("__LEGEND_ROWS__", legend_rows)
    page = page.replace("__THREE_DATA_URI__", _vendor_data_uri("three.module.min.js"))
    page = page.replace("__ORBITCONTROLS_DATA_URI__", _vendor_data_uri("OrbitControls.js"))
    page = page.replace("__CSS2DRENDERER_DATA_URI__", _vendor_data_uri("CSS2DRenderer.js"))
    return page
