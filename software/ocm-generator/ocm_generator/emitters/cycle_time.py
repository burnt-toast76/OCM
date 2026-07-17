# SPDX-License-Identifier: AGPL-3.0-or-later
"""Render a CycleTimeReport as a plain-text table -- the first output a
manufacturing engineer actually reads (see .planner.cycle_time's own
module docstring for what ESTIMATE / nominal_duration_s / overlapped
mean).
"""

from __future__ import annotations

from ocm_generator.planner import CycleTimeReport, FasteningPlan
from ocm_generator.planner.cycle_time import estimate_cycle_time


def render_cycle_time_table(plan: FasteningPlan, report: CycleTimeReport | None = None) -> str:
    """`report` can be precomputed (e.g. with a non-default joint speed);
    defaults to `estimate_cycle_time(plan)`.
    """
    if report is None:
        report = estimate_cycle_time(plan)

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
    lines.append(f"  {'naive serial total:'.ljust(label_width)}  {report.naive_serial_total_s:8.2f} s")
    lines.append(f"  {'with load_screw overlap:'.ljust(label_width)}  {report.overlapped_total_s:8.2f} s")
    savings_pct = (report.savings_s / report.naive_serial_total_s * 100.0) if report.naive_serial_total_s else 0.0
    lines.append(f"  {'overlap savings:'.ljust(label_width)}  {report.savings_s:8.2f} s  ({savings_pct:.1f}%)")
    lines.append("")
    lines.append(
        f"  ESTIMATE = max joint delta / {report.joint_speed_rad_s:.2f} rad/s (a stated default -- "
        "no jerk-limited trajectory generation yet; see ADR-0007)"
    )
    lines.append("  nominal_duration_s = declared in the module's own manifest")
    lines.append("  overlapped = load_screw's own duration, absorbed into the transit beside it")

    return "\n".join(lines) + "\n"
