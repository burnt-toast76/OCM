# SPDX-License-Identifier: AGPL-3.0-or-later
"""ocm_generator.emitters -- render a planned motion (ocm_generator.planner)
as text or as a viewable artifact. `urscript` for a real controller to run
(ADR-0007's "emitted as URScript" for the robot program; PLCopen XML is
future work), `cycle_time` for the manufacturing-engineer-facing summary
table, `animation` to embed and play that same planned motion back in the
self-contained HTML viewer (`ocm plan --view-animation`).
"""

from .animation import AnimationError, build_animation_payload, render_html_animation
from .cycle_time import render_cycle_time_table
from .urscript import emit_urscript

__all__ = [
    "AnimationError",
    "build_animation_payload",
    "emit_urscript",
    "render_cycle_time_table",
    "render_html_animation",
]
