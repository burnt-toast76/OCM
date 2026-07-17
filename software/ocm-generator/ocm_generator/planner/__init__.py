# SPDX-License-Identifier: AGPL-3.0-or-later
"""ocm_generator.planner -- plan a cell's full for_each fastening
sequence's motion: standoff/contact/retract poses for every item,
IK-checked and branch-consistent, and a collision-checked joint-space path
for every segment between them. Everything past scene composition in
ADR-0007's pipeline (`scene/ -> planner/ -> emitters/ -> validate/`) that
this v0 actually implements.

Reachability (.ik) and the joint-path check (.path) both need a real
Tesseract backend, imported lazily -- only `plan_fastening_sequence` (and
thus `ocm plan --emit-urscript`) needs the `tesseract` extra; importing
this package does not.
"""

from .errors import (
    NoDriveScrewStepError,
    PathCollisionError,
    PlanningError,
    PlanningUnavailable,
    PoseUnreachableError,
)
from .cycle_time import CycleTimeReport, CycleTimeRow, estimate_cycle_time
from .ik import UR_JOINT_ORDER, solve_ur_ik
from .plan import FasteningPlan, HolePose, PathSegment, plan_fastening_sequence
from .poses import (
    DriveScrewStep,
    FastenPlan,
    ToolPoses,
    compute_flange_poses,
    compute_part_datum_world,
    contact_step_number,
    find_fastening_plan,
    standoff_step_number,
)

__all__ = [
    "CycleTimeReport",
    "CycleTimeRow",
    "DriveScrewStep",
    "FastenPlan",
    "FasteningPlan",
    "HolePose",
    "NoDriveScrewStepError",
    "PathCollisionError",
    "PathSegment",
    "PlanningError",
    "PlanningUnavailable",
    "PoseUnreachableError",
    "ToolPoses",
    "UR_JOINT_ORDER",
    "compute_flange_poses",
    "compute_part_datum_world",
    "contact_step_number",
    "estimate_cycle_time",
    "find_fastening_plan",
    "plan_fastening_sequence",
    "solve_ur_ik",
    "standoff_step_number",
]
