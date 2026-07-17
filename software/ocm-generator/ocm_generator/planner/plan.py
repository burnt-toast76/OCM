# SPDX-License-Identifier: AGPL-3.0-or-later
"""Plan the first drive_screw step's motion: standoff/contact/retract
flange poses, IK-checked reachability, and a collision-checked home->
standoff joint-space path. Orchestrates .poses / .ik / .path into a single
DriveScrewPlan that .emitters.urscript turns into text.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass

from ocm_resolve import ResolvedCell

from ocm_generator.scene import Pose, Scene, compute_world_poses
from ocm_generator.scene.build import WORLD_LINK

from .errors import PlanningError
from .ik import UR_JOINT_ORDER, solve_ur_ik
from .path import DEFAULT_PATH_SAMPLES, check_joint_path
from .poses import compute_flange_poses, compute_part_datum_world, find_first_drive_screw_step

DEFAULT_COLLISION_MARGIN_MM = 1.0


@dataclass(frozen=True)
class DriveScrewPlan:
    """Everything .emitters.urscript needs to render movej/movel text."""

    tool_instance: str
    robot_instance: str
    hole_id: str
    home_joints: tuple[float, ...]  # radians, UR_JOINT_ORDER
    standoff_joints: tuple[float, ...]  # radians, UR_JOINT_ORDER
    contact_pose_base: Pose  # relative to the UR controller's own "Base" frame
    retract_pose_base: Pose  # relative to the UR controller's own "Base" frame
    approach_speed_m_s: float


def _robot_instance_for(resolved: ResolvedCell, tool_instance: str) -> str:
    tool_ri = resolved.instance(tool_instance)
    if tool_ri.mounted_on is None:
        raise PlanningError(f"{tool_instance} is not mounted on a robot (mount.on is required for planning)")
    return tool_ri.mounted_on.name


def plan_drive_screw(
    resolved: ResolvedCell,
    scene: Scene,
    collision_margin_mm: float = DEFAULT_COLLISION_MARGIN_MM,
    path_samples: int = DEFAULT_PATH_SAMPLES,
) -> DriveScrewPlan:
    """Plan the first drive_screw step's motion end to end.

    Raises NoDriveScrewStepError if the plan has none, PoseUnreachableError
    (naming "standoff" or "contact") if the UR IK solver can't reach either
    pose, PathCollisionError (naming the colliding pair) if the home->
    standoff joint-space path collides, or PlanningUnavailable if the
    `tesseract` extra isn't installed. Never raises on the retract move --
    the capability's own approach vector already designed that channel to
    be clear, and re-verifying a straight pull-out is out of this v0's
    scope (see .path's module docstring).
    """
    step = find_first_drive_screw_step(resolved.cell)
    robot_instance = _robot_instance_for(resolved, step.tool_instance)

    root = ET.fromstring(scene.urdf_xml)
    world_poses = compute_world_poses(root, scene.joint_state, WORLD_LINK)

    _, part_datum_world = compute_part_datum_world(resolved, scene, world_poses)

    tool_ri = resolved.instance(step.tool_instance)
    tool_poses = compute_flange_poses(step, resolved.cell.part, part_datum_world, tool_ri.module)

    base_link = f"{robot_instance}__base_link"
    controller_base_link = f"{robot_instance}__base"
    flange_link = scene.instance(step.tool_instance).parent_link

    if base_link not in world_poses:
        raise PlanningError(f"scene has no world pose for {robot_instance}'s base link {base_link!r}")
    world_t_base_link = world_poses[base_link]
    world_t_controller_base = world_poses.get(controller_base_link, world_t_base_link)

    home_joints = tuple(scene.joint_state.get(f"{robot_instance}__{joint}", 0.0) for joint in UR_JOINT_ORDER)

    standoff_base_link = world_t_base_link.inverse().compose(tool_poses.standoff)
    contact_base_link = world_t_base_link.inverse().compose(tool_poses.contact)

    standoff_joints = solve_ur_ik(
        scene.urdf_xml, base_link, flange_link, standoff_base_link, seed=home_joints, pose_name="standoff"
    )
    solve_ur_ik(
        scene.urdf_xml, base_link, flange_link, contact_base_link, seed=standoff_joints, pose_name="contact"
    )

    check_joint_path(
        scene=scene,
        robot_instance=robot_instance,
        start_joints=home_joints,
        end_joints=standoff_joints,
        samples=path_samples,
        collision_margin_mm=collision_margin_mm,
    )

    contact_controller_base = world_t_controller_base.inverse().compose(tool_poses.contact)
    retract_controller_base = world_t_controller_base.inverse().compose(tool_poses.retract)

    return DriveScrewPlan(
        tool_instance=step.tool_instance,
        robot_instance=robot_instance,
        hole_id=step.hole_id,
        home_joints=home_joints,
        standoff_joints=standoff_joints,
        contact_pose_base=contact_controller_base,
        retract_pose_base=retract_controller_base,
        approach_speed_m_s=tool_poses.approach_speed_m_s,
    )
