# SPDX-License-Identifier: AGPL-3.0-or-later
"""Cycle-time row/report types and the motion-duration estimate, consumed
by `.timeline`'s in-order walk of `cell.plan` (ADR-0029 D1) -- the walk
itself lives there; this module holds what a row IS.

## What "ESTIMATE" means here

Motion row durations are `max(|delta_joint|) / DEFAULT_JOINT_SPEED_RAD_S`
-- a single, generic, DECLARED assumption, not this cell's actual
jerk-limited trajectory time (no Ruckig yet -- see ADR-0007). Every motion
row is labeled ESTIMATE for exactly that reason: this is the first output
a manufacturing engineer actually reads, and it should never be mistaken
for a number a real trajectory generator committed to. Stationary rows
(dwell/actuation) are NOT estimates -- they're each module's own declared
`nominal_duration_s`, carried through unchanged. That distinction is why a
viewer can caption a segment with the number the printed cycle-time table
shows rather than a separately-computed one (ADR-0029 D3).

## Strictly serial (ADR-0029 D4)

The timeline is a total order: `total_s` is the plain sum of every row.
The old `load_screw`-overlaps-a-transit special case -- `source ==
"overlapped"`, `overlapped_with`, and the naive/overlapped/savings total
triple -- is gone with the concurrency it described. The reported cycle
time got longer, and that is the correct direction: a model that reports a
cycle longer than the real machine never oversells it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

DEFAULT_JOINT_SPEED_RAD_S = 1.0


def joint_distance(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    """The slowest single joint's swing, radians -- what actually bounds a
    coordinated multi-joint move's duration, not a Euclidean blend of axes
    that don't share a real-world speed limit.
    """
    return max(abs(x - y) for x, y in zip(a, b))


@dataclass(frozen=True)
class CycleTimeRow:
    label: str
    duration_s: float
    source: str  # "ESTIMATE" (motion) | "nominal_duration_s" (a declared stationary/actuation duration)
    kind: str  # "motion" | "actuation" | "dwell" -- what produced the row's frames (ADR-0029 D3)
    # The label of the row IMMEDIATELY PRECEDING this one, whose final
    # frame is this dwell's own held pose -- set only on dwell rows; None
    # for motion/actuation rows (which own real per-frame motion of their
    # own) and for a dwell that precedes every other row (held at the
    # scene's own initial authored state). Renamed from phase 1's
    # `held_at_segment`: with actuation rows now carrying checked frames
    # (D6), the predecessor a dwell holds is not necessarily a
    # PathSegment -- a dwell after `clamp` holds the clamp sweep's final
    # frame, jaws closed, never a frame captured before the jaws moved.
    held_at: str | None = None
    # The non-robot joint state in effect at the START of this row, keyed
    # `instance__joint` in URDF-native units, accumulated by the timeline
    # walk as actuation rows move module joints. D5 checks each motion
    # row against it (via the scene the walk hands to the checker).
    module_state: dict[str, float] = field(default_factory=dict)
    # Every state this row puts on screen, in order, each one already
    # collision-checked (ADR-0029 D6's invariant: there is only one grade
    # of frame). Motion rows carry check_joint_segment's samples,
    # actuation rows carry check_actuation_segment's sweep, and a dwell
    # carries exactly ONE frame -- its predecessor's final state. This is
    # what the trace serialises (D7).
    frames: tuple[dict[str, float], ...] = ()


@dataclass(frozen=True)
class CycleTimeReport:
    rows: tuple[CycleTimeRow, ...]
    total_s: float  # the plain serial sum of every row -- D4: no overlap, no savings
    joint_speed_rad_s: float
