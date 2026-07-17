# SPDX-License-Identifier: AGPL-3.0-or-later
"""Estimate the fastening sequence's cycle time from a FasteningPlan --
per-segment motion estimates (joint distance / a stated default joint
speed), op durations from each capability's own declared
`nominal_duration_s`, and the overlap savings `load_screw` buys by running
concurrently with the transit into its hole (see .plan's own module
docstring for why that specific transit, and .emitters.urscript for where
its PLC-handshake placeholder actually lands in the emitted script).

## What "ESTIMATE" means here

Motion segment durations are `max(|delta_joint|) / DEFAULT_JOINT_SPEED_RAD_S`
-- a single, generic, DECLARED assumption, not this cell's actual
jerk-limited trajectory time (no Ruckig yet -- see ADR-0007). Every motion
row is labeled ESTIMATE for exactly that reason: this is the first output
a manufacturing engineer actually reads, and it should never be mistaken
for a number a real trajectory generator committed to. Op durations
(`load_screw`/`drive_screw`) are NOT estimates -- they're each module's own
declared `nominal_duration_s`, carried through unchanged.

## The overlap savings

`load_screw_i`'s handshake runs concurrently with the transit into hole i
(duration `transit`), not serially after it. The combined wall-clock time
for that pair is `max(load, transit)`, not `load + transit`; the savings
is `min(load, transit)` -- correct whichever one is longer, and 0 if
there's no load_screw op in the sequence at all.
"""

from __future__ import annotations

from dataclasses import dataclass

from .plan import FasteningPlan

DEFAULT_JOINT_SPEED_RAD_S = 1.0


def _joint_distance(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    """The slowest single joint's swing, radians -- what actually bounds a
    coordinated multi-joint move's duration, not a Euclidean blend of axes
    that don't share a real-world speed limit.
    """
    return max(abs(x - y) for x, y in zip(a, b))


@dataclass(frozen=True)
class CycleTimeRow:
    label: str
    duration_s: float
    source: str  # "ESTIMATE" (motion) | "nominal_duration_s" (a stationary op) | "overlapped" (a load_screw hidden inside a transit)
    overlapped_with: str | None = None  # the segment label this op's duration is hidden inside, if source == "overlapped"


@dataclass(frozen=True)
class CycleTimeReport:
    rows: tuple[CycleTimeRow, ...]
    naive_serial_total_s: float
    overlapped_total_s: float
    savings_s: float
    joint_speed_rad_s: float


def estimate_cycle_time(plan: FasteningPlan, joint_speed_rad_s: float = DEFAULT_JOINT_SPEED_RAD_S) -> CycleTimeReport:
    """Walk `plan.segments` in travel order, interleaving each hole's
    `drive_screw` (right after its approach segment reaches contact) and
    `load_screw` (overlapping the transit into that hole, if the sequence
    has one) -- the same order .emitters.urscript renders as text.
    """
    rows: list[CycleTimeRow] = []
    naive_total = 0.0
    savings = 0.0
    load_screw_done_for: set[str] = set()

    for segment in plan.segments:
        duration = _joint_distance(segment.start_joints, segment.end_joints) / joint_speed_rad_s
        rows.append(CycleTimeRow(label=segment.label, duration_s=duration, source="ESTIMATE"))
        naive_total += duration

        if (
            segment.kind == "transit"
            and segment.hole_id is not None
            and plan.load_screw_module is not None
            and plan.load_screw_nominal_duration_s is not None
            and segment.hole_id not in load_screw_done_for
        ):
            load_screw_done_for.add(segment.hole_id)
            load_duration = plan.load_screw_nominal_duration_s
            rows.append(
                CycleTimeRow(
                    label=f"load_screw @ {segment.hole_id} (overlaps {segment.label})",
                    duration_s=load_duration,
                    source="overlapped",
                    overlapped_with=segment.label,
                )
            )
            naive_total += load_duration
            savings += min(load_duration, duration)

        if segment.kind == "approach" and segment.hole_id is not None and plan.drive_screw_nominal_duration_s is not None:
            drive_duration = plan.drive_screw_nominal_duration_s
            rows.append(
                CycleTimeRow(label=f"drive_screw @ {segment.hole_id}", duration_s=drive_duration, source="nominal_duration_s")
            )
            naive_total += drive_duration

    return CycleTimeReport(
        rows=tuple(rows),
        naive_serial_total_s=naive_total,
        overlapped_total_s=naive_total - savings,
        savings_s=savings,
        joint_speed_rad_s=joint_speed_rad_s,
    )
