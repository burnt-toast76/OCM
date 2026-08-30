# SPDX-License-Identifier: AGPL-3.0-or-later
"""ocm_generator.emitters -- render a planned timeline (ocm_generator.
planner) as text or as a viewable artifact. `urscript` for a real
controller to run (ADR-0007's "emitted as URScript" for the robot
program; PLCopen XML is future work), `cycle_time` for the
manufacturing-engineer-facing summary table, `trace` for THE artifact --
the timeline serialised as JSON (`ocm plan --emit-trace`, ADR-0029 D7) --
and `animation` to render that same trace as the self-contained animated
HTML viewer (`ocm plan --view-animation`): one description of what the
cell does, HTML one way of looking at it.
"""

from .animation import AnimationError, build_animation_payload, render_html_animation
from .cycle_time import render_cycle_time_table
from .trace import build_trace
from .urscript import emit_urscript

__all__ = [
    "AnimationError",
    "build_animation_payload",
    "build_trace",
    "emit_urscript",
    "render_cycle_time_table",
    "render_html_animation",
]
