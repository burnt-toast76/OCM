# SPDX-License-Identifier: AGPL-3.0-or-later
"""Find the first forward drive_screw step in a cell's plan, and compute
the flange-frame standoff/contact/retract poses it needs from the part
feature it targets and the capability's own motion block.

## v0 scope: where the part actually is

`locate_part`'s real vision result isn't modeled -- this isn't a live
simulator any more than .scene.kinematics is (see that module's own
docstring). Instead, the part is assumed seated exactly at whatever
fixture the plan's own `clamp` step names: that fixture's manifest
declares a `part_datum` frame -- "where a correctly seated part's own
origin lands... what cam1's locate_part corrects against" (see
com.accelsolutions.fixture.pneumatic-nest's own manifest note). Using it
directly isn't a simulation of the vision system; it's the exact nominal
placement that system exists to verify.

## Frame math

Every `cell.part.features.*` entry is `xyz_mm`/`normal`, both expressed in
the fixture's own `part_datum` frame. The capability's `motion` block
(`frame: tcp`) expresses `approach_vec`/`retract_vec` in the *tool's own*
TCP frame -- which, for sd50, shares its rotation exactly with the flange
(its `tcp` frame's `rpy_deg` is the schema default, identity), so a single
rotation serves both: point the tool's local +Z (sd50's own note: "+Z
points away from flange, i.e. INTO the screw") anti-parallel to the
feature's outward normal, then walk that rotation's own local axes by
`approach_mm`/`retract_mm` to get standoff/retract from contact. The
result is computed directly in the FLANGE frame (not TCP), since a fixed,
known, purely-translational offset (sd50's own `tcp` frame) is all that
separates the two, and the flange pose is what IK actually needs.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from ocm_core import Module
from ocm_core.cell import Cell
from ocm_resolve import ResolvedCell

from ocm_generator.scene import Pose, Scene
from ocm_generator.scene.transforms import Vec3

from .errors import NoDriveScrewStepError, PlanningError


@dataclass(frozen=True)
class DriveScrewStep:
    """The first forward (non on_fail) drive_screw step in a plan, with its
    enclosing for_each item already substituted into `at`.
    """

    tool_instance: str  # e.g. "sd1"
    hole_id: str  # e.g. "hole_1" -- the for_each item bound at this step
    at_path: str  # e.g. "part.features.hole_1"
    params: dict[str, Any]


@dataclass(frozen=True)
class ToolPoses:
    """Flange-frame (world) poses for one drive_screw step's motion."""

    standoff: Pose
    contact: Pose
    retract: Pose
    approach_speed_m_s: float


def _substitute_item(value: Any, item: str | None) -> Any:
    if isinstance(value, str) and item is not None:
        return value.replace("${item}", item)
    return value


def _walk_forward(plan: list[Any], item: str | None) -> DriveScrewStep | None:
    """Depth-first search of `plan`'s forward path: `for_each` (its first
    item only -- "the first drive_screw step") and `sequence`, but never
    `on_fail`, since that's recovery, not the forward path this plans
    motion for.
    """
    for entry in plan:
        if not isinstance(entry, dict):
            continue

        for_each = entry.get("for_each")
        sequence = entry.get("sequence")
        if isinstance(for_each, list) and isinstance(sequence, list):
            if not for_each:
                continue
            found = _walk_forward(sequence, str(for_each[0]))
            if found is not None:
                return found
            continue

        if entry.get("op") == "drive_screw" and "module" in entry:
            at_path = _substitute_item(entry.get("at", ""), item)
            return DriveScrewStep(
                tool_instance=entry["module"],
                hole_id=item or "",
                at_path=at_path,
                params=dict(entry.get("params", {})),
            )

        if isinstance(sequence, list):
            found = _walk_forward(sequence, item)
            if found is not None:
                return found

    return None


def find_first_drive_screw_step(cell: Cell) -> DriveScrewStep:
    """Raises NoDriveScrewStepError if the plan has no forward drive_screw
    step (an on_fail recovery step doesn't count).
    """
    step = _walk_forward(cell.plan, None)
    if step is None:
        raise NoDriveScrewStepError(f"cell {cell.id!r}'s plan has no (non on_fail) drive_screw step")
    return step


def _find_clamp_fixture(plan: list[Any]) -> str | None:
    for entry in plan:
        if isinstance(entry, dict) and entry.get("op") == "clamp" and "module" in entry:
            return entry["module"]
    return None


def compute_part_datum_world(resolved: ResolvedCell, scene: Scene, world_poses: dict[str, Pose]) -> tuple[str, Pose]:
    """(fixture_instance_name, world pose of its part_datum frame).

    The plan's own `clamp` step names which fixture the part is seated in;
    that fixture's `part_datum` frame is where a correctly-seated part's
    own origin lands (see module docstring).
    """
    fixture_name = _find_clamp_fixture(resolved.cell.plan)
    if fixture_name is None:
        raise PlanningError("plan has no 'clamp' step -- can't tell which fixture the part is seated in")

    fixture_ri = resolved.instances.get(fixture_name)
    if fixture_ri is None:
        raise PlanningError(f"clamp step names unknown module instance {fixture_name!r}")

    part_datum = fixture_ri.module.mechanical.frames.get("part_datum")
    if part_datum is None:
        raise PlanningError(f"{fixture_ri.module.id} declares no mechanical.frames.part_datum")

    fixture_root_link = scene.instance(fixture_name).root_link
    if fixture_root_link not in world_poses:
        raise PlanningError(f"scene has no world pose for {fixture_name}'s root link {fixture_root_link!r}")

    fixture_origin_world = world_poses[fixture_root_link]
    part_datum_local = Pose.from_xyz_rpy(_mm(part_datum.xyz_mm), _deg_to_rad(part_datum.rpy_deg))
    return fixture_name, fixture_origin_world.compose(part_datum_local)


def _resolve_at(part: dict[str, Any] | None, at_path: str) -> dict[str, Any]:
    if part is None:
        raise PlanningError(f"at={at_path!r} references cell.part, but this cell has no part: block")
    segments = at_path.split(".")
    if not segments or segments[0] != "part":
        raise PlanningError(f"at={at_path!r}: expected a 'part.<...>' path")

    node: Any = part
    walked = "part"
    for segment in segments[1:]:
        if not isinstance(node, dict) or segment not in node:
            raise PlanningError(f"at={at_path!r}: {walked!r} has no {segment!r}")
        node = node[segment]
        walked = f"{walked}.{segment}"

    if not isinstance(node, dict) or "xyz_mm" not in node:
        raise PlanningError(f"at={at_path!r}: does not resolve to a feature with 'xyz_mm'")
    return node


def _mm(xyz_mm: Vec3) -> Vec3:
    return (xyz_mm[0] / 1000.0, xyz_mm[1] / 1000.0, xyz_mm[2] / 1000.0)


def _deg_to_rad(rpy_deg: Vec3) -> Vec3:
    return (math.radians(rpy_deg[0]), math.radians(rpy_deg[1]), math.radians(rpy_deg[2]))


def _add(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _sub(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _scale(v: Vec3, s: float) -> Vec3:
    return (v[0] * s, v[1] * s, v[2] * s)


def _negate(v: Vec3) -> Vec3:
    return (-v[0], -v[1], -v[2])


def compute_flange_poses(
    step: DriveScrewStep,
    cell_part: dict[str, Any] | None,
    part_datum_world: Pose,
    tool_module: Module,
) -> ToolPoses:
    """Standoff/contact/retract poses for the tool's FLANGE, in world frame.

    Raises PlanningError if the target feature can't be resolved, or the
    tool module doesn't declare the frames/motion this needs (a `tcp`
    frame, and drive_screw's own `motion` block with approach_vec/
    approach_mm/approach_speed_mm_s).
    """
    feature = _resolve_at(cell_part, step.at_path)
    feature_local_xyz = _mm(tuple(feature["xyz_mm"]))
    feature_local_normal: Vec3 = tuple(feature.get("normal", (0.0, 0.0, 1.0)))

    feature_world_position = part_datum_world.transform_point(feature_local_xyz)
    feature_world_normal = part_datum_world.rotate_vector(feature_local_normal)

    capability = tool_module.capability("drive_screw")
    motion = capability.motion
    if motion is None or motion.approach_vec is None or motion.approach_mm is None:
        raise PlanningError(f"{tool_module.id}'s drive_screw capability declares no usable motion block")
    if motion.approach_speed_mm_s is None:
        raise PlanningError(f"{tool_module.id}'s drive_screw motion declares no approach_speed_mm_s")

    tcp_frame = tool_module.mechanical.tcp
    if tcp_frame is None:
        raise PlanningError(f"{tool_module.id} declares no mechanical.frames.tcp")
    tcp_offset_local = _mm(tuple(tcp_frame.xyz_mm))

    # The tool's local +Z is the bit's own drive axis ("+Z points away from
    # flange, i.e. INTO the screw" -- sd50's own frame note): point it
    # anti-parallel to the feature's outward normal so the bit drives IN.
    contact_rotation = Pose.from_z_axis((0.0, 0.0, 0.0), _negate(feature_world_normal))
    tcp_offset_world = contact_rotation.rotate_vector(tcp_offset_local)
    contact_flange_position = _sub(feature_world_position, tcp_offset_world)
    contact_flange = Pose(contact_flange_position, contact_rotation.rotation)

    approach_dir_world = contact_flange.rotate_vector(motion.approach_vec)
    standoff_flange = Pose(
        _sub(contact_flange_position, _scale(approach_dir_world, motion.approach_mm / 1000.0)),
        contact_flange.rotation,
    )

    retract_vec = motion.retract_vec or _negate(motion.approach_vec)
    retract_mm = motion.retract_mm or motion.approach_mm
    retract_dir_world = contact_flange.rotate_vector(retract_vec)
    retract_flange = Pose(
        _add(contact_flange_position, _scale(retract_dir_world, retract_mm / 1000.0)),
        contact_flange.rotation,
    )

    return ToolPoses(
        standoff=standoff_flange,
        contact=contact_flange,
        retract=retract_flange,
        approach_speed_m_s=motion.approach_speed_mm_s / 1000.0,
    )
