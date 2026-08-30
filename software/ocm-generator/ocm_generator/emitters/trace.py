# SPDX-License-Identifier: AGPL-3.0-or-later
"""ADR-0029 D7: the emitted artifact is a TRACE -- the timeline,
serialised -- and HTML is one consumer of it.

`build_trace` turns a Timeline into plain JSON-able data: the ordered
rows (label, kind, source, duration, held_at, and every already-checked
frame as a namespaced joint-state dict), the serial total, the static
scene payload the debug viewer already speaks (`scene_to_payload`,
reused, not re-derived), and enough of the scene's structure -- the
composed URDF, the link->instance map, the instance kinds, the authored
base joint state -- for a renderer to run forward kinematics per frame
without ever touching the planner. `ocm plan --emit-trace` writes exactly
this as JSON; `--view-animation` renders the same object.

Without this, ADR-0030's `ocm-viewer` would reimplement sequencing and
the cell would acquire two descriptions of what it does -- precisely what
ADR-0027 was written to prevent, one layer up. The trace is the
interface; every frame in it was sampled and proved collision-free (D6's
invariant), so a consumer needs no notion of a second grade of frame.
"""

from __future__ import annotations

from typing import Any

from ocm_resolve import ResolvedCell

from ocm_generator.planner import Timeline
from ocm_generator.scene import Scene
from ocm_generator.scene.viewer import _instance_kinds, scene_to_payload


def build_trace(scene: Scene, resolved: ResolvedCell, timeline: Timeline) -> dict[str, Any]:
    """The timeline as plain JSON-able data (see module docstring). The
    same dict serialised to disk and handed to `render_html_animation`
    directly are interchangeable -- nothing here survives only in memory.
    """
    links: dict[str, str] = {name: "base" for name in scene.base.link_names}
    for instance_name, inst in scene.instances.items():
        for name in inst.link_names:
            links[name] = instance_name

    return {
        "cell_id": resolved.cell.id,
        "total_s": timeline.total_s,
        "joint_speed_rad_s": timeline.joint_speed_rad_s,
        "rows": [
            {
                "label": row.label,
                "kind": row.kind,
                "source": row.source,
                "duration_s": row.duration_s,
                "held_at": row.held_at,
                "frames": [dict(frame) for frame in row.frames],
            }
            for row in timeline.rows
        ],
        "scene": scene_to_payload(scene, resolved),
        "urdf_xml": scene.urdf_xml,
        "links": links,
        "instance_kinds": _instance_kinds(resolved),
        "base_joint_state": dict(scene.joint_state),
    }
