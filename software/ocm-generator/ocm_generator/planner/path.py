# SPDX-License-Identifier: AGPL-3.0-or-later
"""Joint-space linear interpolation between two named configurations,
collision-checked at ~50 sampled states with the existing discrete contact
checker (.scene.collision.check_collisions).

Deliberately a straight line in joint space, not a planned/optimized path
-- OMPL/TrajOpt are out of scope for this v0. A straight line that collides
is REFUSED, not routed around: "the most valuable output of this tool is
'no'" (README.md's own thesis) applies here too. Both endpoints can each be
individually collision-free and the straight line between them still
punch through something a real path planner would route around -- that is
exactly the case this exists to catch, and refusing it is correct v0
behavior, not a defect in this checker.

`.plan` calls this once per segment of the full fastening sequence -- not
just home->standoff, but standoff->contact, contact->retract, and every
inter-hole retract->standoff transit too (see .plan's own module
docstring for why even the short contact/retract moves are checked here,
despite being emitted as `movel`s the controller solves its own path for).

## The interpolated states are worth keeping, not just checking

Every sampled joint-angle tuple this function walks is returned, in order
-- the exact same states already run through a real discrete collision
check, at the exact same joint-space interpolation the emitted URScript
segment corresponds to. `.scene.animation` reuses these directly to drive
`ocm plan --view-animation`'s per-frame forward kinematics: an animation
frame is only ever a state that has *already* been proven collision-free,
never a separately-interpolated (and unchecked) one.
"""

from __future__ import annotations

import dataclasses

from ocm_generator.scene import Scene, check_collisions
from ocm_generator.scene.collision import DEFAULT_MARGIN_MM

from .errors import PathCollisionError
from .ik import UR_JOINT_ORDER

DEFAULT_PATH_SAMPLES = 50


def check_joint_segment(
    scene: Scene,
    robot_instance: str,
    label: str,
    start_joints: tuple[float, ...],
    end_joints: tuple[float, ...],
    samples: int = DEFAULT_PATH_SAMPLES,
    collision_margin_mm: float = DEFAULT_MARGIN_MM,
) -> tuple[tuple[float, ...], ...]:
    """Raises PathCollisionError, naming `label` (e.g. "retract_1 ->
    standoff_2"), the colliding instance pair, and the fraction along the
    path (0=start, 1=end), at the first sampled state (walking from
    `start_joints` towards `end_joints`) that collides.

    Returns every sampled joint-angle tuple (UR_JOINT_ORDER, radians), in
    order, on success -- see module docstring.
    """
    joint_names = [f"{robot_instance}__{joint}" for joint in UR_JOINT_ORDER]
    sampled: list[tuple[float, ...]] = []

    for i in range(samples):
        t = i / (samples - 1) if samples > 1 else 1.0
        interpolated = tuple(start + t * (end - start) for start, end in zip(start_joints, end_joints))
        sampled.append(interpolated)

        joint_state = dict(scene.joint_state)
        joint_state.update(zip(joint_names, interpolated))
        sample_scene = dataclasses.replace(scene, joint_state=joint_state)

        result = check_collisions(sample_scene, contact_distance_mm=collision_margin_mm)
        if result.violations:
            v = result.violations[0]
            raise PathCollisionError(label, v.instance_a, v.instance_b, v.link_a, v.link_b, t)

    return tuple(sampled)
