# SPDX-License-Identifier: AGPL-3.0-or-later
"""Render a CycleTimeReport as a plain-text table -- the first output a
manufacturing engineer actually reads (see .planner.cycle_time's own
module docstring for what ESTIMATE / nominal_duration_s mean). The rows
come from .planner.timeline's in-order walk (ADR-0029 D1); the total is
the plain serial sum (D4 -- no overlap, no savings line).
"""

from __future__ import annotations

from ocm_generator.planner import CycleTimeReport, FasteningPlan


def render_cycle_time_table(plan: FasteningPlan, report: CycleTimeReport) -> str:
    label_width = max([len(row.label) for row in report.rows] + [len("segment/op")])

    lines = [
        f"Cycle time estimate: {plan.tool_instance} fastening sequence ({len(plan.holes)} hole(s))",
        "",
        f"  {'segment/op'.ljust(label_width)}  time (s)  source",
        f"  {'-' * label_width}  --------  ------------------",
    ]

    for row in report.rows:
        lines.append(f"  {row.label.ljust(label_width)}  {row.duration_s:8.2f}  {row.source}")

    lines.append(f"  {'-' * label_width}  --------  ------------------")
    lines.append(f"  {'total:'.ljust(label_width)}  {report.total_s:8.2f} s")
    lines.append("")
    lines.append(
        f"  ESTIMATE = max joint delta / {report.joint_speed_rad_s:.2f} rad/s (a stated default -- "
        "no jerk-limited trajectory generation yet; see ADR-0007)"
    )
    lines.append("  nominal_duration_s = declared in the module's own manifest")

    return "\n".join(lines) + "\n"
