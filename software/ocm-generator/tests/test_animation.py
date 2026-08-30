# SPDX-License-Identifier: AGPL-3.0-or-later
"""ocm_generator.emitters.animation -- `ocm plan --view-animation`'s data
contract: every animation frame is a state `.planner.path.
check_joint_segment` already interpolated and collision-checked (never
recomputed), segments chain continuously, and the total captioned
duration matches the printed cycle-time table exactly. Guarded by the
optional `tesseract` extra, same as test_planner.py -- building the
FasteningPlan still needs it, even though rendering the HTML doesn't.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("tesseract_robotics")

from ocm_core.cell import Cell  # noqa: E402
from ocm_generator.emitters import build_animation_payload, build_trace, render_html_animation  # noqa: E402
from ocm_generator.planner import build_timeline, plan_fastening_sequence  # noqa: E402
from ocm_generator.scene import build_scene, render_html  # noqa: E402
from ocm_resolve import resolve_cell  # noqa: E402

_HOME_JOINT_STATE = {"shoulder_lift_joint": -1.5707963267948966, "elbow_joint": 1.5707963267948966}
_BRACKET_HOLES = {"hole_1": [12, 12, 0], "hole_2": [12, 88, 0], "hole_3": [64, 50, 0]}


def _animation_cell_dict(features: dict[str, list[float]], for_each: list[str]) -> dict[str, Any]:
    """Same real UR5e/sd50/pneumatic-nest/frame1200, camera-free cell
    shape test_planner.py's own fixtures use, for the same reason (IK is
    UR5e-specific; part_datum is pneumatic-nest's own frame).
    """
    return {
        "ocm_version": "1.0",
        "kind": "cell",
        "id": "com.example.cell.animation-test",
        "name": "Animation test cell",
        "license": "CERN-OHL-S-2.0",
        "base": {"module": "com.accelsolutions.base.frame1200@2.0.0", "datum": "cell_origin", "grid": "ocm-base-grid-50"},
        "modules": [
            {
                "instance": "robot1",
                "module": "com.universal-robots.ur5e@3.1.0",
                "mount": {"station": [400, 300], "pose": {"xyz_mm": [400, 300, 0], "rpy_deg": [0, 0, 0]}},
                "joint_state": dict(_HOME_JOINT_STATE),
            },
            {
                "instance": "sd1",
                "module": "com.accelsolutions.screwdriver.sd50@1.2.0",
                "mount": {"on": "robot1.flange"},
                # Same binding the real cell carries -- see test_planner.py.
                "requires": {"workpiece_secured": "nest1.clamped"},
            },
            {
                "instance": "nest1",
                "module": "com.accelsolutions.fixture.pneumatic-nest@1.1.0",
                "mount": {"pose": {"xyz_mm": [640, 300, 0], "rpy_deg": [0, 0, 90]}},
            },
        ],
        "part": {
            "id": "BRK-TEST",
            "cad": "cad/BRK-TEST.step",
            "features": {name: {"xyz_mm": xyz, "normal": [0, 0, 1]} for name, xyz in features.items()},
        },
        "plan": [
            {"step": "clamp", "module": "nest1", "op": "clamp", "params": {"force_n": 120}},
            {
                "step": "fasten",
                "for_each": for_each,
                "sequence": [
                    {"module": "sd1", "op": "load_screw"},
                    {
                        "module": "sd1",
                        "op": "drive_screw",
                        "at": "part.features.${item}",
                        "params": {"torque_nm": 2.4, "depth_mm": 8.0},
                        "on_fail": [{"module": "sd1", "op": "eject_screw"}, {"action": "reject_part"}],
                    },
                ],
            },
            {"step": "release", "module": "nest1", "op": "unclamp"},
        ],
    }


def _build(repo_root: Path, features: dict[str, list[float]], for_each: list[str], path_samples: int = 50):
    cell = Cell.from_dict(_animation_cell_dict(features, for_each))
    resolved = resolve_cell(cell, repo_root / "modules")
    scene = build_scene(resolved, repo_root / "modules")
    plan = plan_fastening_sequence(resolved, scene)
    timeline = build_timeline(resolved, scene, plan, path_samples=path_samples)
    # D7: the trace is the artifact; every emitter test below consumes it.
    return resolved, scene, timeline, build_trace(scene, resolved, timeline)


# ---------------------------------------------------------------------------
# Frame count == the collision-checker's own state count, per segment
# ---------------------------------------------------------------------------


def test_motion_segment_frame_count_equals_the_collision_checkers_sample_count(repo_root: Path):
    path_samples = 37  # deliberately not the default 50, to prove this isn't hardcoded either place
    resolved, scene, timeline, trace = _build(repo_root, _BRACKET_HOLES, ["hole_1", "hole_2", "hole_3"], path_samples=path_samples)

    payload = build_animation_payload(trace)

    motion_segments = [seg for seg in payload["animation"] if seg["kind"] == "motion"]
    assert motion_segments, "expected at least one motion segment"
    for seg in motion_segments:
        assert len(seg["frames"]) == path_samples, (seg["name"], len(seg["frames"]))

    # And a motion segment's frame count matches its own CHECKED
    # PathSegment's frame count exactly -- the actual claim being tested,
    # not just "both happen to equal path_samples". The checked copies
    # live on the Timeline (D5 moved the check pass there).
    segments_by_label = {s.label: s for s in timeline.segments}
    for seg in motion_segments:
        path_segment = segments_by_label[seg["name"]]
        assert len(seg["frames"]) == len(path_segment.frames)


def test_dwell_segments_have_exactly_one_held_frame(repo_root: Path):
    resolved, scene, timeline, trace = _build(repo_root, _BRACKET_HOLES, ["hole_1", "hole_2", "hole_3"])

    payload = build_animation_payload(trace)

    held_segments = [seg for seg in payload["animation"] if seg["kind"] != "motion"]
    # ADR-0029 D1's in-order walk: nest1's clamp/unclamp bracket the
    # sequence (dwells -- the real nest declares no actuates), and each
    # hole reads load_screw (BEFORE its own transit, where the plan lists
    # it -- the overlap special case is gone, D4) then drive_screw:
    # 2 + 3 holes * 2 = 8 held rows, each exactly one frame.
    assert len(held_segments) == 8
    for seg in held_segments:
        assert len(seg["frames"]) == 1, (seg["name"], len(seg["frames"]))
    names = [seg["name"] for seg in held_segments]
    assert names == [
        "nest1.clamp",
        "load_screw @ hole_1",
        "drive_screw @ hole_1",
        "load_screw @ hole_2",
        "drive_screw @ hole_2",
        "load_screw @ hole_3",
        "drive_screw @ hole_3",
        "nest1.unclamp",
    ]


# ---------------------------------------------------------------------------
# Continuity: first frame of segment N+1 == last frame of segment N
# ---------------------------------------------------------------------------


def test_consecutive_segments_share_a_frame_at_the_boundary(repo_root: Path):
    resolved, scene, timeline, trace = _build(repo_root, _BRACKET_HOLES, ["hole_1", "hole_2", "hole_3"])

    payload = build_animation_payload(trace)
    animation = payload["animation"]
    assert len(animation) >= 2

    for a, b in zip(animation, animation[1:]):
        assert a["frames"][-1] == b["frames"][0], f"discontinuity between {a['name']!r} and {b['name']!r}"


# ---------------------------------------------------------------------------
# Total captioned duration matches the cycle-table total
# ---------------------------------------------------------------------------


def test_total_duration_matches_the_cycle_table_total(repo_root: Path):
    resolved, scene, timeline, trace = _build(repo_root, _BRACKET_HOLES, ["hole_1", "hole_2", "hole_3"])

    payload = build_animation_payload(trace)

    assert payload["total_duration_s"] == pytest.approx(timeline.total_s)
    # And it's genuinely the sum of every segment's own duration -- not a
    # coincidentally-equal separately-computed number (D4: the total IS
    # the plain serial sum; there is no overlapped variant to disagree).
    assert payload["total_duration_s"] == pytest.approx(sum(seg["duration_s"] for seg in payload["animation"]))
    # Sanity: every row in the printed cycle table produced exactly one
    # animation segment -- nothing dropped, nothing invented.
    assert len(payload["animation"]) == len(timeline.rows)


# ---------------------------------------------------------------------------
# Static modules emit once; dynamic (robot + sd1) primitives are separate
# ---------------------------------------------------------------------------


def test_static_primitives_exclude_the_robot_and_its_tool(repo_root: Path):
    resolved, scene, timeline, trace = _build(repo_root, {"hole_1": [12, 12, 0]}, ["hole_1"])

    payload = build_animation_payload(trace)
    dynamic_instances = {p["instance"] for p in payload["dynamic_primitives"]}

    assert dynamic_instances == {"robot1", "sd1"}
    for prim in payload["dynamic_primitives"]:
        assert "position" not in prim  # per-frame, not baked into the static template
        assert "quaternion" not in prim


def test_html_static_primitives_exclude_dynamic_instances(repo_root: Path):
    resolved, scene, timeline, trace = _build(repo_root, {"hole_1": [12, 12, 0]}, ["hole_1"])

    page = render_html_animation(trace)
    data = _extract_data(page)

    static_instances = {p["instance"] for p in data["primitives"]}
    assert "robot1" not in static_instances
    assert "sd1" not in static_instances
    assert "nest1" in static_instances or "base" in static_instances


# ---------------------------------------------------------------------------
# The rendered HTML: vendored three.js (no CDN), valid JSON payload,
# player UI present. Static --view output stays untouched.
# ---------------------------------------------------------------------------


def _extract_data(page: str) -> dict[str, Any]:
    match = re.search(r"const DATA = (.*?);\n\nconst scene", page, re.S)
    assert match, "couldn't find `const DATA = ...;` in the rendered page"
    return json.loads(match.group(1))


def test_animated_html_vendors_three_js_with_no_cdn_reference(repo_root: Path):
    resolved, scene, timeline, trace = _build(repo_root, {"hole_1": [12, 12, 0]}, ["hole_1"])

    page = render_html_animation(trace)

    assert "unpkg.com" not in page
    assert "cdn" not in page.lower()
    assert page.count("data:text/javascript;base64,") == 3  # three, OrbitControls, CSS2DRenderer

    match = re.search(r'<script type="importmap">\n(.*?)\n</script>', page, re.S)
    import_map = json.loads(match.group(1))
    for url in import_map["imports"].values():
        assert url.startswith("data:text/javascript;base64,")


def test_animated_html_has_playback_controls_and_valid_data(repo_root: Path):
    resolved, scene, timeline, trace = _build(repo_root, _BRACKET_HOLES, ["hole_1", "hole_2", "hole_3"])

    page = render_html_animation(trace)

    assert 'id="playPause"' in page
    assert 'id="scrub"' in page
    assert 'id="speed"' in page
    assert 'id="caption"' in page
    assert 'value="0.5"' in page and 'value="2"' in page  # speed options

    data = _extract_data(page)
    assert len(data["animation"]) == len(timeline.rows)
    assert data["total_duration_s"] == pytest.approx(timeline.total_s)


def test_static_view_output_is_unchanged_by_the_animation_feature(repo_root: Path):
    # render_html (the plain `ocm scene --view`) must still load three.js
    # from the CDN import map -- only --view-animation vendors it.
    resolved, scene, timeline, trace = _build(repo_root, {"hole_1": [12, 12, 0]}, ["hole_1"])

    page = render_html(scene, resolved)

    assert "unpkg.com" in page
    assert "data:text/javascript;base64," not in page
