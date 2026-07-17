# SPDX-License-Identifier: AGPL-3.0-or-later
"""ocm_generator.emitters -- render a planned motion (ocm_generator.planner)
as text a real controller can run. Just URScript for now (ADR-0007's
"emitted as URScript" for the robot program); PLCopen XML is future work.
"""

from .urscript import emit_urscript

__all__ = ["emit_urscript"]
