# SPDX-License-Identifier: AGPL-3.0-or-later
"""ocm_generator -- cell.yaml -> Tesseract scene -> collision-checked motion
-> URScript/PLCopen XML. See ROADMAP Step 1.

Only `scene/` exists so far: it compiles a ResolvedCell (ocm_resolve) into a
real tesseract_robotics Environment. `planner/`, `emitters/`, and
`validate/` are future work.
"""

from .errors import OcmGeneratorError

__all__ = ["OcmGeneratorError"]
