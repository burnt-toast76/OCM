# SPDX-License-Identifier: AGPL-3.0-or-later
"""ocm_generator.planner -- plan a cell's first drive_screw step's motion:
standoff/contact/retract poses, IK-checked reachability, and a collision-
checked home->standoff joint-space path. Everything past scene composition
in ADR-0007's pipeline (`scene/ -> planner/ -> emitters/ -> validate/`) that
this v0 actually implements.

Reachability (.ik) and the joint-path check (.path) both need a real
Tesseract backend, imported lazily -- only `plan_drive_screw` (and thus
`ocm plan --emit-urscript`) needs the `tesseract` extra; importing this
package does not.
"""

from .errors import (
    NoDriveScrewStepError,
    PathCollisionError,
    PlanningError,
    PlanningUnavailable,
    PoseUnreachableError,
)
from .ik import UR_JOINT_ORDER, solve_ur_ik
from .plan import DriveScrewPlan, plan_drive_screw
from .poses import (
    DriveScrewStep,
    ToolPoses,
    compute_flange_poses,
    compute_part_datum_world,
    find_first_drive_screw_step,
)

__all__ = [
    "DriveScrewPlan",
    "DriveScrewStep",
    "NoDriveScrewStepError",
    "PathCollisionError",
    "PlanningError",
    "PlanningUnavailable",
    "PoseUnreachableError",
    "ToolPoses",
    "UR_JOINT_ORDER",
    "compute_flange_poses",
    "compute_part_datum_world",
    "find_first_drive_screw_step",
    "plan_drive_screw",
    "solve_ur_ik",
]
