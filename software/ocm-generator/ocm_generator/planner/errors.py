# SPDX-License-Identifier: AGPL-3.0-or-later
"""Errors raised by ocm_generator.planner. Same shape as ocm_generator.scene's
own errors: a refusal that names exactly what it's refusing, not a bare
exception -- "the most valuable output of this tool is 'no'" (README.md)
applies just as much to motion planning as it does to scene composition.
"""

from __future__ import annotations

from ocm_generator.errors import OcmGeneratorError


class PlanningError(OcmGeneratorError):
    """Base class for every refusal ocm_generator.planner can raise."""


class NoDriveScrewStepError(PlanningError):
    """The cell's plan has no forward (non on_fail) drive_screw step."""


class PoseUnreachableError(PlanningError):
    """The UR analytic IK solver found no solution for a named pose (e.g.
    "standoff_2")."""

    def __init__(self, pose_name: str, detail: str = ""):
        self.pose_name = pose_name
        message = f"pose {pose_name!r} is not reachable by the UR IK solver"
        if detail:
            message += f": {detail}"
        super().__init__(message)


class PathCollisionError(PlanningError):
    """A segment's straight-line joint-space path collides at some sampled
    state, even though the individual endpoints may each be collision-free.
    """

    def __init__(self, segment: str, instance_a: str, instance_b: str, link_a: str, link_b: str, fraction: float):
        self.segment = segment
        self.instance_a = instance_a
        self.instance_b = instance_b
        self.link_a = link_a
        self.link_b = link_b
        self.fraction = fraction
        super().__init__(
            f"segment {segment!r} collides at t={fraction:.3f}: "
            f"{instance_a} <-> {instance_b} ({link_a} / {link_b})"
        )


class PlanningUnavailable(PlanningError):
    """tesseract-robotics isn't installed, or no IK/collision backend could
    be loaded from it. Same shape as scene.collision.CollisionCheckUnavailable.
    """


class PlanStepUnplannableError(PlanningError):
    """A plan step's capability declares no `at:` target, no `actuates`
    (ADR-0028), and no `nominal_duration_s` -- nothing to place on a
    timeline (ADR-0029 D1)."""

    def __init__(self, step: str, instance: str, op: str):
        self.step = step
        self.instance = instance
        self.op = op
        super().__init__(
            f"plan step {step!r} calls {instance}.{op}, which declares no 'at:' target, "
            "no actuates, and no nominal_duration_s -- nothing to place on a timeline"
        )


class ActuationDurationMissingError(PlanningError):
    """A capability declares `actuates` but no `nominal_duration_s`: the
    endpoint is stated, the time is not, and it will not be invented
    (ADR-0029's fabrication guard)."""

    def __init__(self, instance: str, module_id: str, capability: str):
        self.instance = instance
        self.module_id = module_id
        self.capability = capability
        super().__init__(
            f"capability {capability!r} on {module_id} (instance {instance}) declares "
            "actuates but no nominal_duration_s -- the endpoint is stated, the time is "
            "not, and it will not be invented"
        )
