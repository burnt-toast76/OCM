# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared forward kinematics over a composed URDF: world poses per link,
and every collision primitive a link carries (not just the first).

Split out from the viewer so the same, single implementation backs both
the debug viewer (ocm_generator.scene.viewer) and the workspace
containment check (ocm_generator.scene.containment) -- two different
consumers computing where things physically are should never be two
different pieces of FK math that can quietly drift apart.

Revolute/continuous joints rotate about their <axis> by the value given in
an (optional) joint_state map (namespaced joint name -> radians); anything
absent from that map -- and every prismatic joint, and every fixed joint --
is evaluated at zero/its bare <origin>. That is a deliberate simplification
for a static snapshot (a debug view, a one-off containment check), not a
live simulator.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Optional

from .transforms import Pose, Vec3

JointState = dict[str, float]

_MOVABLE_JOINT_TYPES = ("revolute", "continuous", "prismatic")


def _origin_pose(elem: Optional[ET.Element]) -> Pose:
    if elem is None:
        return Pose.identity()
    xyz = tuple(float(v) for v in elem.get("xyz", "0 0 0").split())
    rpy = tuple(float(v) for v in elem.get("rpy", "0 0 0").split())
    return Pose.from_xyz_rpy(xyz, rpy)  # type: ignore[arg-type]


def _axis_of(joint: ET.Element) -> Vec3:
    axis_el = joint.find("axis")
    if axis_el is None or not axis_el.get("xyz"):
        return (0.0, 0.0, 1.0)  # URDF's own default
    return tuple(float(v) for v in axis_el.get("xyz").split())  # type: ignore[return-value]


def _joint_motion(joint: ET.Element, joint_state: JointState) -> Pose:
    """The joint's OWN configurable motion (beyond its fixed <origin>):
    identity unless it's revolute/continuous/prismatic AND joint_state
    gives it a value.
    """
    joint_type = joint.get("type", "fixed")
    if joint_type not in _MOVABLE_JOINT_TYPES:
        return Pose.identity()
    name = joint.get("name")
    if name not in joint_state:
        return Pose.identity()

    value = joint_state[name]
    axis = _axis_of(joint)
    if joint_type == "prismatic":
        return Pose((axis[0] * value, axis[1] * value, axis[2] * value))
    return Pose.from_axis_angle(axis, value)


def compute_world_poses(
    root: ET.Element, joint_state: Optional[JointState] = None, world_link: str = "world"
) -> dict[str, Pose]:
    """BFS every joint in the composed URDF from `world_link`, composing
    each joint's <origin> (then any joint_state motion) along the chain.
    """
    joint_state = joint_state or {}

    children: dict[str, list[tuple[ET.Element, str]]] = {}
    for joint in root.findall("joint"):
        parent_el = joint.find("parent")
        child_el = joint.find("child")
        if parent_el is None or child_el is None:
            continue
        parent_name = parent_el.get("link")
        child_name = child_el.get("link")
        if not parent_name or not child_name:
            continue
        children.setdefault(parent_name, []).append((joint, child_name))

    poses: dict[str, Pose] = {world_link: Pose.identity()}
    frontier = [world_link]
    while frontier:
        next_frontier: list[str] = []
        for parent_name in frontier:
            parent_pose = poses[parent_name]
            for joint, child_name in children.get(parent_name, []):
                local = _origin_pose(joint.find("origin"))
                motion = _joint_motion(joint, joint_state)
                poses[child_name] = parent_pose.compose(local).compose(motion)
                next_frontier.append(child_name)
        frontier = next_frontier
    return poses


@dataclass(frozen=True)
class GeometryPrimitive:
    kind: str  # "box" | "cylinder" | "sphere"
    dims: dict[str, float]
    world: Pose
    placeholder: bool  # True for the mesh-fallback marker -- not a real collision shape


def list_collision_primitives(link: ET.Element, link_world: Pose) -> list[GeometryPrimitive]:
    """Every <collision> a link carries (a link may have several -- e.g. a
    base module's deck slab plus its guard walls, all on one link), not
    just the first.
    """
    results: list[GeometryPrimitive] = []
    for collision in link.findall("collision"):
        geometry = collision.find("geometry")
        if geometry is None:
            continue
        world = link_world.compose(_origin_pose(collision.find("origin")))

        box = geometry.find("box")
        if box is not None and box.get("size"):
            x, y, z = (float(v) for v in box.get("size").split())
            results.append(GeometryPrimitive("box", {"x": x, "y": y, "z": z}, world, False))
            continue

        cylinder = geometry.find("cylinder")
        if cylinder is not None:
            radius = float(cylinder.get("radius", "0.02"))
            length = float(cylinder.get("length", "0.05"))
            results.append(GeometryPrimitive("cylinder", {"radius": radius, "length": length}, world, False))
            continue

        sphere = geometry.find("sphere")
        if sphere is not None:
            results.append(GeometryPrimitive("sphere", {"radius": float(sphere.get("radius", "0.02"))}, world, False))
            continue

        mesh = geometry.find("mesh")
        if mesh is not None:
            # No STL/mesh loader in the debug viewer, and no real bounding
            # info cheaply available here either -- a small marker/estimate
            # stands in. See viewer.py's module docstring.
            results.append(GeometryPrimitive("sphere", {"radius": 0.035}, world, True))
            continue

    return results


def world_aabb(prim: GeometryPrimitive) -> tuple[Vec3, Vec3]:
    """The primitive's axis-aligned world bounding box, as (min, max).

    Exact for box and sphere. For cylinder, conservative: computed as its
    circumscribing box (2*radius x 2*radius x length) rotated the same way
    -- always >= the cylinder's true AABB, which is the safe direction for
    a containment/refusal check to be wrong in.
    """
    if prim.kind == "sphere":
        r = prim.dims["radius"]
        cx, cy, cz = prim.world.translation
        return (cx - r, cy - r, cz - r), (cx + r, cy + r, cz + r)

    if prim.kind == "box":
        hx, hy, hz = prim.dims["x"] / 2.0, prim.dims["y"] / 2.0, prim.dims["z"] / 2.0
    else:  # cylinder
        r, length = prim.dims["radius"], prim.dims["length"]
        hx, hy, hz = r, r, length / 2.0

    corners = [
        prim.world.transform_point((sx * hx, sy * hy, sz * hz))
        for sx in (-1.0, 1.0)
        for sy in (-1.0, 1.0)
        for sz in (-1.0, 1.0)
    ]
    xs = [c[0] for c in corners]
    ys = [c[1] for c in corners]
    zs = [c[2] for c in corners]
    return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))
