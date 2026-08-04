# SPDX-License-Identifier: AGPL-3.0-or-later
"""Render a TRACE (ADR-0029 D7 -- `.emitters.trace.build_trace`'s output,
in memory or read back from the JSON `ocm plan --emit-trace` wrote) as
the same self-contained HTML viewer `ocm_generator.scene.viewer` builds
statically, animated -- `ocm plan --view-animation`.

This module is a CONSUMER of the trace, not a second producer: it never
touches the planner, never re-interpolates a path, never re-derives
sequencing. Every frame it draws is a joint-state dict the timeline
already collision-checked (D6's invariant: one grade of frame), run
through the same forward kinematics (`.scene.kinematics.
compute_world_poses`) the static viewer and the workspace containment
check use, to get link poses to draw.

## Rows

`DATA.animation` is a flat, ordered list matching the trace's rows
one-for-one -- literally the same rows the printed cycle-time table
shows, so a segment's caption and duration in the viewer are the exact
numbers in that table. Motion and actuation rows carry their full checked
sweep; a dwell carries exactly ONE frame -- its predecessor's final state
(so a dwell after `clamp` shows the jaws closed, never a frame captured
before they moved). The pause is real and visible: this is where
spec/08's handshake actually lives -- see spec/08-robot-handshake.md.

No smoothing, no retiming: playback is linear between whatever frames were
actually checked, at a constant per-frame timestep within each motion
segment (`duration_s / (len(frames) - 1)`). Honest v0 -- jerk-limited
timing arrives with Ruckig later (ADR-0007).

## Dynamic vs static geometry

Dynamic is derived from the FRAMES THEMSELVES, not from mount topology:
a joint whose value varies anywhere across the trace makes every link
downstream of it move, and every instance owning such a link is dynamic
-- the robot and whatever rides its flange, but equally a nest whose jaw
an actuation row sweeps. Everything else is emitted once, exactly as the
plain `--view` output already does (the trace embeds `scene_to_payload`'s
own output, reused directly and filtered) -- a static module's mesh is
built once in JS and never touched again during playback.

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

from ocm_generator.errors import OcmGeneratorError
from ocm_generator.scene.build import WORLD_LINK
from ocm_generator.scene.kinematics import compute_world_poses, list_collision_primitives
from ocm_generator.scene.transforms import Pose

_VENDOR_DIR = Path(__file__).resolve().parent.parent / "scene" / "vendor" / "three"


class AnimationError(OcmGeneratorError):
    """The trace is internally inconsistent (e.g. a row with no frames) --
    a producer bug, not a user-facing refusal: `.planner.timeline` gives
    every row at least one checked frame by construction.
    """


def _varying_joints(trace: dict[str, Any]) -> set[str]:
    """Every joint whose value differs anywhere across the trace's frames
    (or from the authored base state) -- the trace's own answer to "what
    moves?", replacing any assumption about mount topology: a robot moves,
    but so does a nest jaw an actuation row sweeps.
    """
    base = trace["base_joint_state"]
    reference: dict[str, float] = {}
    varying: set[str] = set()
    for row in trace["rows"]:
        for frame in row["frames"]:
            for name, value in frame.items():
                first = reference.setdefault(name, base.get(name, value))
                if value != first:
                    varying.add(name)
    return varying


def _dynamic_instances(root: ET.Element, trace: dict[str, Any]) -> set[str]:
    """Every instance owning a link DOWNSTREAM of a varying joint. The
    joints come from the frames themselves (`_varying_joints`); the walk
    down the URDF tree is what carries "robot1's wrist moves" into "sd1
    (bolted to the flange) needs a fresh pose every frame" -- and "nest1's
    jaw sweeps" into nest1 being dynamic -- without consulting mount
    topology at all.
    """
    joints_by_parent: dict[str, list[ET.Element]] = {}
    for joint in root.findall("joint"):
        parent = joint.find("parent")
        if parent is not None and parent.get("link"):
            joints_by_parent.setdefault(parent.get("link"), []).append(joint)

    varying = _varying_joints(trace)
    stack: list[str | None] = [
        joint.find("child").get("link")
        for joint in root.findall("joint")
        if joint.get("name") in varying and joint.find("child") is not None
    ]
    dynamic_links: set[str] = set()
    while stack:
        link = stack.pop()
        if not link or link in dynamic_links:
            continue
        dynamic_links.add(link)
        for joint in joints_by_parent.get(link, []):
            child = joint.find("child")
            if child is not None:
                stack.append(child.get("link"))

    links_to_instance = trace["links"]
    return {links_to_instance[link] for link in dynamic_links if link in links_to_instance}


def _dynamic_link_names(trace: dict[str, Any], dynamic_instances: set[str]) -> set[str]:
    return {link for link, instance in trace["links"].items() if instance in dynamic_instances}


def _dynamic_primitive_specs(root: ET.Element, dynamic_link_names: set[str], trace: dict[str, Any]) -> list[dict[str, Any]]:
    """Static metadata only (kind/dims/instance/instance_kind/link/
    placeholder) for every dynamic-instance collision primitive, in URDF
    document order -- that order is authoritative: every animation frame's
    per-primitive transform list (`_frame_transforms`) is built by the
    exact same walk, so the two stay index-aligned by construction.
    """
    instance_kinds = trace["instance_kinds"]
    links_to_instance = trace["links"]
    specs: list[dict[str, Any]] = []
    for link in root.findall("link"):
        name = link.get("name")
        if not name or name not in dynamic_link_names:
            continue
        instance = links_to_instance.get(name, "?")
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


def build_animation_payload(trace: dict[str, Any]) -> dict[str, Any]:
    """Everything the animated viewer needs beyond the trace's own static
    scene payload: dynamic-primitive metadata (built once) and the ordered
    `animation` list, one entry per trace row, each carrying real
    per-frame transforms computed from the row's own already-checked
    frames -- see module docstring.
    """
    root = ET.fromstring(trace["urdf_xml"])
    dynamic_instances = _dynamic_instances(root, trace)
    dynamic_link_names = _dynamic_link_names(trace, dynamic_instances)
    dynamic_primitives = _dynamic_primitive_specs(root, dynamic_link_names, trace)

    animation: list[dict[str, Any]] = []
    for row in trace["rows"]:
        if not row["frames"]:
            raise AnimationError(f"trace row {row['label']!r} carries no frames")
        animation.append(
            {
                "name": row["label"],
                "kind": row["kind"],
                "duration_s": row["duration_s"],
                "frames": [_frame_transforms(root, frame, dynamic_link_names) for frame in row["frames"]],
            }
        )

    return {
        "dynamic_primitives": dynamic_primitives,
        "animation": animation,
        "total_duration_s": trace["total_s"],
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


def render_html_animation(trace: dict[str, Any]) -> str:
    """Render a trace (`.emitters.trace.build_trace`'s output, in memory
    or loaded back from `--emit-trace`'s JSON) into one self-contained,
    animated HTML file -- vendored three.js, no CDN, no server, no build
    step. Open by double-clicking. Rendering from the freshly-built dict
    and from its JSON round-trip produces the same page: the trace is the
    interface (ADR-0029 D7), and this is one consumer of it.
    """
    static_payload = dict(trace["scene"])
    dynamic_instances = _dynamic_instances(ET.fromstring(trace["urdf_xml"]), trace)
    static_payload["primitives"] = [p for p in static_payload["primitives"] if p["instance"] not in dynamic_instances]

    animation_payload = build_animation_payload(trace)
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
