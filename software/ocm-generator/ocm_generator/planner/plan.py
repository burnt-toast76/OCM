# SPDX-License-Identifier: AGPL-3.0-or-later
"""Plan the full for_each fastening sequence's motion: standoff/contact/
retract flange poses for every item (not just the first), IK-checked and
branch-consistent across the whole chain, and a collision-checked
straight-line joint-space path for every segment between them --

    home -> standoff_1 -> contact_1 -> retract_1
          -> standoff_2 -> contact_2 -> retract_2
          -> ...
          -> standoff_N -> contact_N -> retract_N -> home

Transits between holes go directly retract_i -> standoff_{i+1}; the robot
only returns home once, at the very end. Items are visited in the plan's
own for_each order -- v0 doesn't reorder or optimize visiting order ("no
path optimization -- v0 is honest").

## IK branch consistency

The UR analytic IK solver returns up to 8 solutions for almost every
reachable pose -- the same Cartesian target is often reachable by several
very different joint configurations ("branches"). Solving each pose
independently, with no regard for what came before, can chain solutions
that are each individually valid but require an enormous, physically
absurd joint swing to get from one to the next (a "branch flip"). Every
pose in the chain is therefore IK-solved seeded by, and selected as
closest (by joint-space distance -- see .ik.solve_ur_ik) to, the
IMMEDIATELY PRECEDING configuration in this sequence -- never re-seeded
from `home`. See test_planner.py's own branch-consistency test, which
pins this down by asserting no consecutive pair in the resulting chain
swings any single joint by more than ~90 degrees.

## Why contact/retract are IK-solved and collision-checked too

They're emitted as `movel` (Cartesian) moves, which the controller solves
its own IK for online -- so their joint config isn't textually needed in
the emitted script. It's still solved and checked here because (1) IK
reachability is itself a refusal-worthy fact about a pose no differently
than standoff's, and (2) it's the seed the NEXT pose in the chain needs
for its own branch selection -- a real UR controller executing a sequence
of movels also picks the IK branch closest to its actual current joint
position, so chaining the same way here keeps this plan's assumptions in
step with what the controller will actually do, not just internally
self-consistent. Both are collision-checked with the same joint-space
linear-interpolation machinery as every other segment (see .path); short,
but not skipped.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, replace

from ocm_resolve import ResolvedCell

from ocm_generator.scene import Pose, Scene, compute_world_poses
from ocm_generator.scene.build import WORLD_LINK

from .errors import PlanningError
from .ik import UR_JOINT_ORDER, solve_ur_ik
from .path import DEFAULT_PATH_SAMPLES, check_joint_segment
from .poses import compute_flange_poses, compute_part_datum_world, find_fastening_plan

DEFAULT_COLLISION_MARGIN_MM = 1.0
_HOME_LABEL = "home"


@dataclass(frozen=True)
class HolePose:
    """One for_each item's standoff/contact/retract."""

    hole_id: str  # the for_each item, e.g. "hole_1"
    index: int  # 1-based visiting order -- what segment/pose-refusal labels use
    standoff_joints: tuple[float, ...]  # radians, UR_JOINT_ORDER
    contact_joints: tuple[float, ...]
    retract_joints: tuple[float, ...]
    contact_pose_base: Pose  # relative to the UR controller's own "Base" frame
    retract_pose_base: Pose


@dataclass(frozen=True)
class PathSegment:
    """One collision-checked joint-space segment of the full sequence, in
    the order the robot actually travels it.
    """

    label: str  # e.g. "retract_1 -> standoff_2"
    kind: str  # "transit" (into a hole's standoff, or the final return home) | "approach" | "withdraw"
    hole_id: str | None  # the hole this segment leads into (transit/approach) or out of (withdraw); None for the final transit home
    start_joints: tuple[float, ...]
    end_joints: tuple[float, ...]
    # Every joint-angle tuple `.path.check_joint_segment` sampled AND
    # already proved collision-free for this exact segment, in travel
    # order (start_joints == frames[0], end_joints == frames[-1]) --
    # `.scene.animation` reuses these directly for `--view-animation`,
    # never re-interpolating its own. Empty until plan_fastening_sequence
    # runs the check (see that function's own two-pass construction).
    frames: tuple[tuple[float, ...], ...] = ()


@dataclass(frozen=True)
class FasteningPlan:
    """Everything .emitters needs to render URScript and a cycle-time
    report for the full fastening sequence.
    """

    tool_instance: str
    robot_instance: str
    home_joints: tuple[float, ...]  # radians, UR_JOINT_ORDER
    holes: tuple[HolePose, ...]  # in visiting order
    segments: tuple[PathSegment, ...]  # in travel order; every one already collision-checked
    approach_speed_m_s: float
    load_screw_module: str | None
    load_screw_nominal_duration_s: float | None
    drive_screw_nominal_duration_s: float | None
    on_fail_summary: str | None  # PLC-side recovery, e.g. "eject_screw, reject_part" -- not emitted as URScript


def _robot_instance_for(resolved: ResolvedCell, tool_instance: str) -> str:
    tool_ri = resolved.instance(tool_instance)
    if tool_ri.mounted_on is None:
        raise PlanningError(f"{tool_instance} is not mounted on a robot (mount.on is required for planning)")
    return tool_ri.mounted_on.name


def _pos_label(kind: str, index: int | None) -> str:
    return _HOME_LABEL if kind == "home" else f"{kind}_{index}"


def plan_fastening_sequence(
    resolved: ResolvedCell,
    scene: Scene,
    collision_margin_mm: float = DEFAULT_COLLISION_MARGIN_MM,
    path_samples: int = DEFAULT_PATH_SAMPLES,
) -> FasteningPlan:
    """Plan the full for_each fastening sequence end to end -- every item,
    in listed order, chained continuously (no return home between holes).

    Raises NoDriveScrewStepError if the plan has no fastening for_each,
    PoseUnreachableError (naming the pose, e.g. "standoff_2") if the UR IK
    solver can't reach it, PathCollisionError (naming the segment, e.g.
    "retract_1 -> standoff_2", and the colliding pair) if any segment's
    straight-line joint-space path collides, or PlanningUnavailable if the
    `tesseract` extra isn't installed.
    """
    fasten = find_fastening_plan(resolved.cell)
    tool_instance = fasten.steps[0].tool_instance
    robot_instance = _robot_instance_for(resolved, tool_instance)
    tool_ri = resolved.instance(tool_instance)

    root = ET.fromstring(scene.urdf_xml)
    world_poses = compute_world_poses(root, scene.joint_state, WORLD_LINK)
    _, part_datum_world = compute_part_datum_world(resolved, scene, world_poses)

    base_link = f"{robot_instance}__base_link"
    controller_base_link = f"{robot_instance}__base"
    flange_link = scene.instance(tool_instance).parent_link

    if base_link not in world_poses:
        raise PlanningError(f"scene has no world pose for {robot_instance}'s base link {base_link!r}")
    world_t_base_link = world_poses[base_link]
    world_t_controller_base = world_poses.get(controller_base_link, world_t_base_link)

    home_joints = tuple(scene.joint_state.get(f"{robot_instance}__{joint}", 0.0) for joint in UR_JOINT_ORDER)

    holes: list[HolePose] = []
    segments: list[PathSegment] = []
    previous_joints = home_joints
    previous_kind, previous_index = "home", None
    approach_speed_m_s = 0.0

    for index, step in enumerate(fasten.steps, start=1):
        tool_poses = compute_flange_poses(step, resolved.cell.part, part_datum_world, tool_ri.module)
        approach_speed_m_s = tool_poses.approach_speed_m_s

        standoff_base_link = world_t_base_link.inverse().compose(tool_poses.standoff)
        contact_base_link = world_t_base_link.inverse().compose(tool_poses.contact)
        retract_base_link = world_t_base_link.inverse().compose(tool_poses.retract)

        standoff_joints = solve_ur_ik(
            scene.urdf_xml, base_link, flange_link, standoff_base_link,
            seed=previous_joints, pose_name=_pos_label("standoff", index),
        )
        segments.append(PathSegment(
            label=f"{_pos_label(previous_kind, previous_index)} -> {_pos_label('standoff', index)}",
            kind="transit",
            hole_id=step.hole_id,
            start_joints=previous_joints,
            end_joints=standoff_joints,
        ))
        previous_joints, previous_kind, previous_index = standoff_joints, "standoff", index

        contact_joints = solve_ur_ik(
            scene.urdf_xml, base_link, flange_link, contact_base_link,
            seed=previous_joints, pose_name=_pos_label("contact", index),
        )
        segments.append(PathSegment(
            label=f"{_pos_label('standoff', index)} -> {_pos_label('contact', index)}",
            kind="approach",
            hole_id=step.hole_id,
            start_joints=previous_joints,
            end_joints=contact_joints,
        ))
        previous_joints, previous_kind, previous_index = contact_joints, "contact", index

        retract_joints = solve_ur_ik(
            scene.urdf_xml, base_link, flange_link, retract_base_link,
            seed=previous_joints, pose_name=_pos_label("retract", index),
        )
        segments.append(PathSegment(
            label=f"{_pos_label('contact', index)} -> {_pos_label('retract', index)}",
            kind="withdraw",
            hole_id=step.hole_id,
            start_joints=previous_joints,
            end_joints=retract_joints,
        ))
        previous_joints, previous_kind, previous_index = retract_joints, "retract", index

        holes.append(HolePose(
            hole_id=step.hole_id,
            index=index,
            standoff_joints=standoff_joints,
            contact_joints=contact_joints,
            retract_joints=retract_joints,
            contact_pose_base=world_t_controller_base.inverse().compose(tool_poses.contact),
            retract_pose_base=world_t_controller_base.inverse().compose(tool_poses.retract),
        ))

    segments.append(PathSegment(
        label=f"{_pos_label(previous_kind, previous_index)} -> {_HOME_LABEL}",
        kind="transit",
        hole_id=None,
        start_joints=previous_joints,
        end_joints=home_joints,
    ))

    checked_segments: list[PathSegment] = []
    for segment in segments:
        frames = check_joint_segment(
            scene=scene,
            robot_instance=robot_instance,
            label=segment.label,
            start_joints=segment.start_joints,
            end_joints=segment.end_joints,
            samples=path_samples,
            collision_margin_mm=collision_margin_mm,
        )
        checked_segments.append(replace(segment, frames=frames))
    segments = checked_segments

    load_screw_nominal_duration_s = None
    if fasten.load_screw_module is not None:
        load_screw_ri = resolved.instance(fasten.load_screw_module)
        load_screw_nominal_duration_s = load_screw_ri.module.capability("load_screw").nominal_duration_s

    return FasteningPlan(
        tool_instance=tool_instance,
        robot_instance=robot_instance,
        home_joints=home_joints,
        holes=tuple(holes),
        segments=tuple(segments),
        approach_speed_m_s=approach_speed_m_s,
        load_screw_module=fasten.load_screw_module,
        load_screw_nominal_duration_s=load_screw_nominal_duration_s,
        drive_screw_nominal_duration_s=tool_ri.module.capability("drive_screw").nominal_duration_s,
        on_fail_summary=fasten.on_fail_summary,
    )
