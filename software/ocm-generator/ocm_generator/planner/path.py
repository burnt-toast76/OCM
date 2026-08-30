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

`.timeline` calls `check_joint_segment` once per motion row of the full
fastening sequence -- not just home->standoff, but standoff->contact,
contact->retract, and every inter-hole retract->standoff transit too (see
.plan's own module docstring for why even the short contact/retract moves
are checked, despite being emitted as `movel`s the controller solves its
own path for) -- and `check_actuation_segment` once per actuation row
(ADR-0029 D6: an actuation row is a segment, checked like any other). The
checks live in the timeline walk, not in `plan_fastening_sequence`,
because the walk is the one place that knows the module state in effect
at each row (D5); the scene each call receives already carries that
accumulated state in its `joint_state`.

## The interpolated states are worth keeping, not just checking

Every sampled state this function walks is returned, in order -- the exact
same states already run through a real discrete collision check, at the
exact same joint-space interpolation the emitted URScript segment
corresponds to. `.emitters.animation` reuses these directly to drive
`ocm plan --view-animation`'s per-frame forward kinematics: an animation
frame is only ever a state that has *already* been proven collision-free,
never a separately-interpolated (and unchecked) one.

A returned frame is the FULL namespaced joint-state dict (ADR-0029 D2) --
the same `dict(scene.joint_state)`-plus-robot-overlay each sample was
collision-checked as, keyed `instance__joint` exactly like
`Scene.joint_state` and `compute_world_poses`. A robot frame and a module
frame are the same kind of thing; IK and Tesseract keep speaking
`UR_JOINT_ORDER` tuples internally, and this is the boundary where that
representation ends.
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
) -> tuple[dict[str, float], ...]:
    """Raises PathCollisionError, naming `label` (e.g. "retract_1 ->
    standoff_2"), the colliding instance pair, and the fraction along the
    path (0=start, 1=end), at the first sampled state (walking from
    `start_joints` towards `end_joints`) that collides.

    Returns every sampled state as a full namespaced joint-state dict
    (radians/metres), in order, on success -- see module docstring.
    """
    joint_names = [f"{robot_instance}__{joint}" for joint in UR_JOINT_ORDER]
    sampled: list[dict[str, float]] = []

    for i in range(samples):
        t = i / (samples - 1) if samples > 1 else 1.0
        interpolated = tuple(start + t * (end - start) for start, end in zip(start_joints, end_joints))

        joint_state = dict(scene.joint_state)
        joint_state.update(zip(joint_names, interpolated))
        sampled.append(joint_state)
        sample_scene = dataclasses.replace(scene, joint_state=joint_state)

        result = check_collisions(sample_scene, contact_distance_mm=collision_margin_mm)
        if result.violations:
            v = result.violations[0]
            raise PathCollisionError(label, v.instance_a, v.instance_b, v.link_a, v.link_b, t)

    return tuple(sampled)


def check_actuation_segment(
    scene: Scene,
    label: str,
    start: dict[str, float],
    end: dict[str, float],
    samples: int = DEFAULT_PATH_SAMPLES,
    collision_margin_mm: float = DEFAULT_MARGIN_MM,
) -> tuple[dict[str, float], ...]:
    """Collision-check one actuation row's sweep (ADR-0029 D6): every
    joint the capability actuates, interpolated linearly TOGETHER across
    the same sample set -- one verb, one sweep. `start`/`end` map each
    actuated joint's namespaced name to its value in URDF-native units;
    everything else (the robot at its accumulated pose included) stays
    where `scene.joint_state` puts it, which is why the caller hands in a
    scene already carrying the state in effect when the row starts.

    Raises the existing PathCollisionError on a violation, naming `label`
    (the row's own label, e.g. "fix1.clamp"), the colliding instance
    pair, and the fraction along the sweep. Returns every sampled state
    as a full namespaced joint-state dict, in order, on success -- the
    same contract as check_joint_segment; an actuation row is a segment.

    What this does NOT catch, stated plainly (ADR-0029 D6):
    `check_collisions` skips contact between two links of the SAME
    instance, so two jaws of one nest closing on each other are not
    checked; and `cell.part` is never placed in the collision scene, so
    nothing checks a jaw closing onto the workpiece. What this catches is
    a module joint sweeping into a DIFFERENT instance -- jaws into a tool
    parked above them, a feeder pusher into the robot.
    """
    keys = sorted(end)
    sampled: list[dict[str, float]] = []

    for i in range(samples):
        t = i / (samples - 1) if samples > 1 else 1.0
        interpolated = {k: start[k] + t * (end[k] - start[k]) for k in keys}

        joint_state = {**scene.joint_state, **interpolated}
        sampled.append(joint_state)
        sample_scene = dataclasses.replace(scene, joint_state=joint_state)

        result = check_collisions(sample_scene, contact_distance_mm=collision_margin_mm)
        if result.violations:
            v = result.violations[0]
            raise PathCollisionError(label, v.instance_a, v.instance_b, v.link_a, v.link_b, t)

    return tuple(sampled)
