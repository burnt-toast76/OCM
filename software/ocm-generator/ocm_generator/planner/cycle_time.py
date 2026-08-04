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
    # The PathSegment.label whose LAST frame is this row's own held pose,
    # if this row is stationary (kind != "motion") -- None for a motion
    # row (which owns real per-frame motion), and None for a stationary
    # row that precedes ALL motion (held at the scene's own initial
    # state). `.emitters.animation` uses this directly, so a held frame is
    # always looked up, never assumed from row order.
    held_at_segment: str | None = None
    # The non-robot joint state in effect at the START of this row, keyed
    # `instance__joint` in URDF-native units, accumulated by the timeline
    # walk as actuation rows move module joints. NOTHING consumes it in
    # ADR-0029 phase 1 -- it is built now because it is the walk's natural
    # output and D5 (state-aware collision checking) is the thing that
    # reads it; building it later would mean walking twice.
    module_state: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class CycleTimeReport:
    rows: tuple[CycleTimeRow, ...]
    total_s: float  # the plain serial sum of every row -- D4: no overlap, no savings
    joint_speed_rad_s: float
