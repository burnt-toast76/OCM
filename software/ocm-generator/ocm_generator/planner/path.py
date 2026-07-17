# SPDX-License-Identifier: AGPL-3.0-or-later
"""Joint-space linear interpolation from home to a standoff, collision-
checked at ~50 sampled states with the existing discrete contact checker
(.scene.collision.check_collisions).

Deliberately a straight line in joint space, not a planned/optimized path
-- OMPL/TrajOpt are out of scope for this v0. A straight line that collides
is REFUSED, not routed around: "the most valuable output of this tool is
'no'" (README.md's own thesis) applies here too. Both endpoints can each be
individually collision-free and the straight line between them still
punch through something a real path planner would route around -- that is
exactly the case this exists to catch, and refusing it is correct v0
behavior, not a defect in this checker.
"""

from __future__ import annotations

import dataclasses

from ocm_generator.scene import Scene, check_collisions
from ocm_generator.scene.collision import DEFAULT_MARGIN_MM

from .errors import PathCollisionError
from .ik import UR_JOINT_ORDER

DEFAULT_PATH_SAMPLES = 50


def check_joint_path(
    scene: Scene,
    robot_instance: str,
    start_joints: tuple[float, ...],
    end_joints: tuple[float, ...],
    samples: int = DEFAULT_PATH_SAMPLES,
    collision_margin_mm: float = DEFAULT_MARGIN_MM,
) -> None:
    """Raises PathCollisionError, naming the colliding instance pair and
    the fraction along the path (0=start, 1=end), at the first sampled
    state (walking from `start_joints` towards `end_joints`) that collides.
    """
    joint_names = [f"{robot_instance}__{joint}" for joint in UR_JOINT_ORDER]

    for i in range(samples):
        t = i / (samples - 1) if samples > 1 else 1.0
        sample_joints = {
            name: start + t * (end - start)
            for name, start, end in zip(joint_names, start_joints, end_joints)
        }
        joint_state = dict(scene.joint_state)
        joint_state.update(sample_joints)
        sample_scene = dataclasses.replace(scene, joint_state=joint_state)

        result = check_collisions(sample_scene, contact_distance_mm=collision_margin_mm)
        if result.violations:
            v = result.violations[0]
            raise PathCollisionError(v.instance_a, v.instance_b, v.link_a, v.link_b, t)
