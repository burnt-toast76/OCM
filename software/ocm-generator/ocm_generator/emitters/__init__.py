# SPDX-License-Identifier: AGPL-3.0-or-later
"""ocm_generator.emitters -- render a planned motion (ocm_generator.planner)
as text. `urscript` for a real controller to run (ADR-0007's "emitted as
URScript" for the robot program; PLCopen XML is future work), `cycle_time`
for the manufacturing-engineer-facing summary table.
"""

from .cycle_time import render_cycle_time_table
from .urscript import emit_urscript

__all__ = ["emit_urscript", "render_cycle_time_table"]
