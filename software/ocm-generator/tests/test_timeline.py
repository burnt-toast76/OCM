# SPDX-License-Identifier: AGPL-3.0-or-later
"""ADR-0029 D1-D6: planner/timeline's in-order walk of cell.plan. The
fastening MOTION producer (plan_fastening_sequence) needs the tesseract
extra, so these tests hand it a synthetic, pre-built FasteningPlan; the
Bullet backend is stubbed out (`no_collision_backend`) so the REAL
check_joint_segment / check_actuation_segment interpolation and the REAL
walk run everywhere -- CI never installs the extra. Modules are the
conftest's synthetic ones with obviously-synthetic capabilities
(ADR-0014: real durations/strokes are the owner's to state)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from ocm_core.cell import Cell
from ocm_generator.planner import (
    ActuationDurationMissingError,
    FasteningPlan,
    HolePose,
    PathSegment,
    PlanStepUnplannableError,
    build_timeline,
)
from ocm_generator.scene import Pose, build_scene
from ocm_resolve import resolve_cell

from .conftest import base_fragment_xml, build_cell_dict, fragment_xml, minimal_base_manifest, minimal_robot_manifest, write_module

# A fixture with one prismatic jaw joint (limits stated inline; synthetic).
_FIX_FRAGMENT = """<?xml version="1.0"?>
<robot name="frag">
  <link name="origin"><collision><geometry><box size="0.05 0.05 0.05"/></geometry></collision></link>
  <link name="jaw"><collision><geometry><box size="0.01 0.01 0.01"/></geometry></collision></link>
  <joint name="jaw" type="prismatic">
    <parent link="origin"/><child link="jaw"/>
    <axis xyz="1 0 0"/>
    <limit lower="0.0" upper="0.02" effort="10" velocity="0.1"/>
  </joint>
</robot>"""


def _tool_manifest() -> dict[str, Any]:
    """A screwdriver-shaped tool: drive_screw (motion + declared drive
    time) and load_screw (a plain dwell)."""
    return {
        "ocm_version": "1.0",
        "id": "com.example.tool.tiny",
        "revision": "1.0.0",
        "kind": "end_effector",
        "license": "CERN-OHL-S-2.0",
        "name": "Tiny Test Tool",
        "mechanical": {
            "mount": {"interface": "iso-9409-1-a50", "footprint_mm": [70, 70]},
            "frames": {"origin": {"xyz_mm": [0, 0, 0]}, "tcp": {"xyz_mm": [0, 0, 100]}},
            "geometry": {"collision": "meshes/tool_convex.stl", "urdf_fragment": "tool.urdf"},
            "mass_kg": 1.0,
            "com_mm": [0, 0, 50],
        },
        "comms": {"protocol": "ethercat", "signals": []},
        "capabilities": [
            {"name": "drive_screw", "summary": "x", "timeout_s": 6.0, "on_timeout": "abort", "nominal_duration_s": 1.8},
            {"name": "load_screw", "summary": "x", "timeout_s": 6.0, "on_timeout": "abort", "nominal_duration_s": 0.9},
        ],
        "state_machine": {"model": "packml", "implements": ["idle", "execute"], "abort_safe": False},
    }


def _fixture_manifest() -> dict[str, Any]:
    """clamp/unclamp are ACTUATION rows (actuates + duration); `vent` has
    nothing to place on a timeline; `surge` states an endpoint but no time."""
    return {
        "ocm_version": "1.1",
        "id": "com.example.fixture.jaws",
        "revision": "1.0.0",
        "kind": "fixture",
        "license": "CERN-OHL-S-2.0",
        "name": "Tiny Test Jaws",
        "mechanical": {
            "mount": {"interface": "custom"},
            # part_datum: ADR-0031 D4 -- the plan operates on `part`, so the
            # part's location must be DECLARED (the old clamp-verb scrape is
            # gone); this fixture is the declaring instance.
            "frames": {"origin": {"xyz_mm": [0, 0, 0]}, "part_datum": {"xyz_mm": [0, 0, 20]}},
            "geometry": {"urdf_fragment": "fix.urdf"},
            "mass_kg": 3.0,
        },
        "capabilities": [
            {"name": "clamp", "summary": "x", "timeout_s": 3.0, "on_timeout": "hold",
             "nominal_duration_s": 0.6, "actuates": [{"joint": "jaw", "to": 8.0, "units": "mm"}]},
            {"name": "unclamp", "summary": "x", "timeout_s": 3.0, "on_timeout": "hold",
             "nominal_duration_s": 0.4, "actuates": [{"joint": "jaw", "to": 0.0, "units": "mm"}]},
            {"name": "vent", "summary": "x", "timeout_s": 3.0, "on_timeout": "hold"},
            {"name": "surge", "summary": "x", "timeout_s": 3.0, "on_timeout": "hold",
             "actuates": [{"joint": "jaw", "to": 2.0, "units": "mm"}]},
        ],
        "state_machine": {"model": "packml", "abort_safe": True},
    }


def _cell_dict(plan: list[Any], for_each_features: list[str]) -> dict[str, Any]:
    cell = build_cell_dict()
    cell["modules"].append({
        "instance": "fix1",
        "module": "com.example.fixture.jaws@1.0.0",
        "mount": {"pose": {"xyz_mm": [600, 300, 0], "rpy_deg": [0, 0, 0]}},
    })
    cell["part"] = {
        "id": "PART-TEST",
        "cad": "cad/PART-TEST.step",
        "features": {name: {"xyz_mm": [10, 10, 0], "normal": [0, 0, 1]} for name in for_each_features},
    }
    cell["plan"] = plan
    return cell


_DOGFOOD_SHAPE_PLAN = [
    {"step": "clamp", "module": "fix1", "op": "clamp"},
    {
        "step": "fasten",
        "for_each": ["hole_1", "hole_2"],
        "sequence": [
            {"module": "tool1", "op": "load_screw"},
            {"module": "tool1", "op": "drive_screw", "at": "part.features.${item}"},
        ],
    },
    {"step": "release", "module": "fix1", "op": "unclamp"},
]


def _resolved_scene(tmp_path: Path, plan: list[Any], for_each_features: list[str] | None = None):
    root = tmp_path / "modules"
    write_module(root, minimal_base_manifest(), "base.urdf", base_fragment_xml("origin"))
    write_module(root, minimal_robot_manifest(), "robot.urdf", fragment_xml("origin", extra_link="flange", extra_xyz=(0.0, 0.0, 0.4)))
    write_module(root, _tool_manifest(), "tool.urdf", fragment_xml("origin"))
    write_module(root, _fixture_manifest(), "fix.urdf", _FIX_FRAGMENT)
    cell = Cell.from_dict(_cell_dict(plan, for_each_features or ["hole_1", "hole_2"]))
    resolved = resolve_cell(cell, root)
    scene = build_scene(resolved, root)
    return resolved, scene


# Small sample count: enough to see interpolation, cheap to assert on.
_SAMPLES = 5


def _joints(x: float, y: float = 0.0) -> tuple[float, ...]:
    return (x, y, 0.0, 0.0, 0.0, 0.0)


def _fake_plan(holes: list[str]) -> FasteningPlan:
    """A synthetic pre-checked FasteningPlan with the real producer's
    segment labeling/kinds. Joint values are chosen so motion durations
    are exact at the default 1.0 rad/s: transit_i = 1.0 s (joint0 swings
    1.0 rad), approach/withdraw = 0.2 s, final home transit = N s.
    """
    home = _joints(0.0)
    segments: list[PathSegment] = []
    hole_poses: list[HolePose] = []
    prev, prev_label = home, "home"
    for i, hole in enumerate(holes, start=1):
        standoff, contact, retract = _joints(float(i)), _joints(float(i), 0.2), _joints(float(i))
        segments.append(PathSegment(label=f"{prev_label} -> standoff_{i}", kind="transit", hole_id=hole, start_joints=prev, end_joints=standoff))
        segments.append(PathSegment(label=f"standoff_{i} -> contact_{i}", kind="approach", hole_id=hole, start_joints=standoff, end_joints=contact))
        segments.append(PathSegment(label=f"contact_{i} -> retract_{i}", kind="withdraw", hole_id=hole, start_joints=contact, end_joints=retract))
        hole_poses.append(HolePose(
            hole_id=hole, index=i,
            standoff_joints=standoff, contact_joints=contact, retract_joints=retract,
            contact_pose_base=Pose.identity(), retract_pose_base=Pose.identity(),
        ))
        prev, prev_label = retract, f"retract_{i}"
    segments.append(PathSegment(label=f"{prev_label} -> home", kind="transit", hole_id=None, start_joints=prev, end_joints=home))
    return FasteningPlan(
        tool_instance="tool1",
        robot_instance="robot1",
        home_joints=home,
        holes=tuple(hole_poses),
        segments=tuple(segments),
        approach_speed_m_s=0.02,
        load_screw_module="tool1",
        load_screw_nominal_duration_s=0.9,
        drive_screw_nominal_duration_s=1.8,
        on_fail_summary=None,
    )


def test_rows_read_in_plan_order(tmp_path: Path, no_collision_backend: None):
    resolved, scene = _resolved_scene(tmp_path, _DOGFOOD_SHAPE_PLAN)
    timeline = build_timeline(resolved, scene, _fake_plan(["hole_1", "hole_2"]), path_samples=_SAMPLES)

    # clamp before fasten before release; for_each in listed order; each
    # hole reads load -> transit -> approach -> drive -> withdraw, and the
    # single return home follows the last hole.
    assert [r.label for r in timeline.rows] == [
        "fix1.clamp",
        "load_screw @ hole_1",
        "home -> standoff_1",
        "standoff_1 -> contact_1",
        "drive_screw @ hole_1",
        "contact_1 -> retract_1",
        "load_screw @ hole_2",
        "retract_1 -> standoff_2",
        "standoff_2 -> contact_2",
        "drive_screw @ hole_2",
        "contact_2 -> retract_2",
        "retract_2 -> home",
        "fix1.unclamp",
    ]


def test_each_step_kind_produces_the_right_row_kind(tmp_path: Path, no_collision_backend: None):
    resolved, scene = _resolved_scene(tmp_path, _DOGFOOD_SHAPE_PLAN)
    timeline = build_timeline(resolved, scene, _fake_plan(["hole_1", "hole_2"]), path_samples=_SAMPLES)

    kinds = {r.label: r.kind for r in timeline.rows}
    assert kinds["fix1.clamp"] == "actuation"  # actuates + nominal_duration_s
    assert kinds["fix1.unclamp"] == "actuation"
    assert kinds["load_screw @ hole_1"] == "dwell"  # nominal_duration_s only
    assert kinds["drive_screw @ hole_1"] == "dwell"
    assert kinds["home -> standoff_1"] == "motion"  # the at: step's segments
    # Sources follow kinds: motion is an ESTIMATE, everything else is a
    # declared nominal_duration_s -- and nothing is "overlapped" (D4).
    for row in timeline.rows:
        assert row.source == ("ESTIMATE" if row.kind == "motion" else "nominal_duration_s")


def test_total_is_the_plain_serial_sum(tmp_path: Path, no_collision_backend: None):
    resolved, scene = _resolved_scene(tmp_path, _DOGFOOD_SHAPE_PLAN)
    timeline = build_timeline(resolved, scene, _fake_plan(["hole_1", "hole_2"]), path_samples=_SAMPLES)

    # Motion (joint swings / 1.0 rad/s): transits 1.0 + 1.0, approaches
    # 0.2 * 2, withdraws 0.2 * 2, final home 2.0  -> 4.8 s.
    # Stated: clamp 0.6 + 2 * (load 0.9 + drive 1.8) + unclamp 0.4 -> 6.4 s.
    assert timeline.total_s == pytest.approx(4.8 + 6.4)
    assert timeline.total_s == pytest.approx(sum(r.duration_s for r in timeline.rows))
    assert timeline.report.total_s == timeline.total_s


def test_for_each_expands_in_listed_order(tmp_path: Path, no_collision_backend: None):
    plan = [dict(_DOGFOOD_SHAPE_PLAN[0]), dict(_DOGFOOD_SHAPE_PLAN[1]), dict(_DOGFOOD_SHAPE_PLAN[2])]
    plan[1] = {**plan[1], "for_each": ["hole_2", "hole_1"]}
    resolved, scene = _resolved_scene(tmp_path, plan)
    # The producer visits items in the same listed order, so index 1 IS hole_2.
    timeline = build_timeline(resolved, scene, _fake_plan(["hole_2", "hole_1"]), path_samples=_SAMPLES)

    labels = [r.label for r in timeline.rows]
    assert labels.index("drive_screw @ hole_2") < labels.index("drive_screw @ hole_1")
    assert labels.index("load_screw @ hole_2") < labels.index("load_screw @ hole_1")


def test_held_at_points_at_the_immediately_preceding_row(tmp_path: Path, no_collision_backend: None):
    resolved, scene = _resolved_scene(tmp_path, _DOGFOOD_SHAPE_PLAN)
    timeline = build_timeline(resolved, scene, _fake_plan(["hole_1", "hole_2"]), path_samples=_SAMPLES)

    held = {r.label: r.held_at for r in timeline.rows}
    # held_at is a dwell's pointer at its IMMEDIATE predecessor, whatever
    # kind that row is (D6 renamed it from held_at_segment: the
    # predecessor here is the clamp ACTUATION row, not a PathSegment).
    assert held["load_screw @ hole_1"] == "fix1.clamp"
    # drive_screw is held at contact -- the approach row precedes it.
    assert held["drive_screw @ hole_1"] == "standoff_1 -> contact_1"
    # load_screw for the NEXT hole is held where the plan left the robot.
    assert held["load_screw @ hole_2"] == "contact_1 -> retract_1"
    # Motion and actuation rows own real frames; they hold nothing.
    assert held["fix1.clamp"] is None
    assert held["fix1.unclamp"] is None
    assert held["home -> standoff_1"] is None


def test_motion_rows_are_checked_against_the_module_state_in_effect(tmp_path: Path, no_collision_backend: None):
    # D5, observable: a transit planned AFTER clamp is checked (and its
    # frames built) with the jaws closed; the same transit in a plan where
    # fastening precedes clamp carries them open.
    resolved, scene = _resolved_scene(tmp_path, _DOGFOOD_SHAPE_PLAN)
    timeline = build_timeline(resolved, scene, _fake_plan(["hole_1", "hole_2"]), path_samples=_SAMPLES)
    rows = {r.label: r for r in timeline.rows}
    for frame in rows["home -> standoff_1"].frames:
        assert frame["fix1__jaw"] == pytest.approx(0.008)  # clamped: 8 mm

    plan_fasten_first = [_DOGFOOD_SHAPE_PLAN[1], dict(_DOGFOOD_SHAPE_PLAN[0])]
    resolved2, scene2 = _resolved_scene(tmp_path, plan_fasten_first)
    timeline2 = build_timeline(resolved2, scene2, _fake_plan(["hole_1", "hole_2"]), path_samples=_SAMPLES)
    rows2 = {r.label: r for r in timeline2.rows}
    for frame in rows2["home -> standoff_1"].frames:
        assert "fix1__jaw" not in frame  # still at the authored state: never moved yet


def test_actuation_rows_carry_a_full_checked_sweep(tmp_path: Path, no_collision_backend: None):
    # D6: an actuation row is real swept motion now, not one held frame.
    resolved, scene = _resolved_scene(tmp_path, _DOGFOOD_SHAPE_PLAN)
    timeline = build_timeline(resolved, scene, _fake_plan(["hole_1", "hole_2"]), path_samples=_SAMPLES)

    clamp = next(r for r in timeline.rows if r.label == "fix1.clamp")
    assert len(clamp.frames) == _SAMPLES
    values = [frame["fix1__jaw"] for frame in clamp.frames]
    assert values[0] == pytest.approx(0.0)
    assert values[-1] == pytest.approx(0.008)
    assert values == sorted(values)  # linear sweep from open to closed

    # unclamp sweeps back down, starting from where clamp left the jaw.
    unclamp = next(r for r in timeline.rows if r.label == "fix1.unclamp")
    assert unclamp.frames[0]["fix1__jaw"] == pytest.approx(0.008)
    assert unclamp.frames[-1]["fix1__jaw"] == pytest.approx(0.0)


def test_dwell_after_actuation_holds_the_post_actuation_state(tmp_path: Path, no_collision_backend: None):
    # Regression for the stale-held-frame hazard D6 creates: the dwell
    # right after clamp must show the jaws CLOSED -- its held frame is the
    # clamp sweep's FINAL frame, never one captured before the jaws moved.
    resolved, scene = _resolved_scene(tmp_path, _DOGFOOD_SHAPE_PLAN)
    timeline = build_timeline(resolved, scene, _fake_plan(["hole_1", "hole_2"]), path_samples=_SAMPLES)

    rows = {r.label: r for r in timeline.rows}
    clamp, load = rows["fix1.clamp"], rows["load_screw @ hole_1"]
    assert len(load.frames) == 1
    assert load.frames[0] == clamp.frames[-1]
    assert load.frames[0]["fix1__jaw"] == pytest.approx(0.008)


def test_every_stationary_row_holds_its_predecessors_final_frame(tmp_path: Path, no_collision_backend: None):
    resolved, scene = _resolved_scene(tmp_path, _DOGFOOD_SHAPE_PLAN)
    timeline = build_timeline(resolved, scene, _fake_plan(["hole_1", "hole_2"]), path_samples=_SAMPLES)

    for previous, row in zip(timeline.rows, timeline.rows[1:]):
        if row.kind == "dwell":
            assert row.frames == (previous.frames[-1],), (row.label, previous.label)


def test_module_state_accumulates_actuation_targets(tmp_path: Path, no_collision_backend: None):
    resolved, scene = _resolved_scene(tmp_path, _DOGFOOD_SHAPE_PLAN)
    timeline = build_timeline(resolved, scene, _fake_plan(["hole_1", "hole_2"]), path_samples=_SAMPLES)

    rows = {r.label: r for r in timeline.rows}
    # Snapshot is the state at the row's START: clamp itself still sees the
    # authored initial state (no fix1__jaw entry -- the cell states none)...
    assert "fix1__jaw" not in rows["fix1.clamp"].module_state
    # ...every row after clamp sees the jaw at 8 mm = 0.008 m, URDF-native...
    assert rows["load_screw @ hole_1"].module_state["fix1__jaw"] == pytest.approx(0.008)
    assert rows["retract_2 -> home"].module_state["fix1__jaw"] == pytest.approx(0.008)
    # ...and unclamp's own snapshot is still pre-unclamp.
    assert rows["fix1.unclamp"].module_state["fix1__jaw"] == pytest.approx(0.008)
    # The robot's own joints never appear -- module_state is non-robot state.
    assert not any(k.startswith("robot1__") for k in rows["fix1.unclamp"].module_state)


def test_unplannable_step_refuses(tmp_path: Path, no_collision_backend: None):
    plan = [
        {"step": "vent", "module": "fix1", "op": "vent"},  # no at, no actuates, no nominal_duration_s
        _DOGFOOD_SHAPE_PLAN[1],
    ]
    resolved, scene = _resolved_scene(tmp_path, plan)

    with pytest.raises(PlanStepUnplannableError) as exc:
        build_timeline(resolved, scene, _fake_plan(["hole_1", "hole_2"]), path_samples=_SAMPLES)

    assert exc.value.instance == "fix1"
    assert exc.value.op == "vent"
    assert "nothing to place on a timeline" in str(exc.value)


def test_actuates_without_duration_refuses(tmp_path: Path, no_collision_backend: None):
    plan = [
        {"step": "surge", "module": "fix1", "op": "surge"},  # actuates, no nominal_duration_s
        _DOGFOOD_SHAPE_PLAN[1],
    ]
    resolved, scene = _resolved_scene(tmp_path, plan)

    with pytest.raises(ActuationDurationMissingError) as exc:
        build_timeline(resolved, scene, _fake_plan(["hole_1", "hole_2"]), path_samples=_SAMPLES)

    assert exc.value.capability == "surge"
    assert "will not be invented" in str(exc.value)
